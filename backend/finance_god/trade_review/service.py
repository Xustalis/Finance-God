from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.profile import DirectionRecommendation, InvestmentProfile
from finance_god.domain import ConcurrentCommandConflict
from finance_god.execution import TradeDecisionContext
from finance_god.infrastructure.persistence.simulation_models import (
    SimulationExecutionEventRow,
    SimulationExecutionOutboxRow,
)
from finance_god.infrastructure.persistence.simulation_repository import (
    simulation_event_digest,
)
from finance_god.infrastructure.persistence.trade_review_models import (
    ProfileFeedbackRow,
    TradeDecisionSnapshotRow,
    TradeEpisodeRow,
    TradeReviewRow,
)

from .models import (
    Availability,
    DecisionField,
    EpisodeStatus,
    ProfileFeedback,
    ReviewStatus,
    TradeDecisionSnapshot,
    TradeEpisode,
    TradeReview,
)

ZERO = Decimal("0")
_LOGGER = logging.getLogger(__name__)
_BACKGROUND_RETRY_INTERVAL = timedelta(seconds=30)


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:20]}"


def _missing(reason: str) -> DecisionField:
    return DecisionField(
        status=Availability.UNAVAILABLE,
        unavailable_reason=reason,
    )


def _available(value: str) -> DecisionField:
    return DecisionField(
        status=Availability.AVAILABLE,
        value=value,
    )


def _aware_datetime(value: object) -> datetime:
    occurred_at = datetime.fromisoformat(str(value))
    if occurred_at.tzinfo is None:
        return occurred_at.replace(tzinfo=UTC)
    return occurred_at


def _position_after(current: Decimal, side: str, quantity: Decimal) -> Decimal:
    if side == "buy":
        return current + quantity
    if side != "sell":
        raise ValueError(f"unsupported trade review side: {side}")
    remaining = current - quantity
    if remaining < ZERO:
        raise ValueError("sell fill exceeds the active trade episode quantity")
    return remaining


def _context_field(
    context: TradeDecisionContext | None,
    name: str,
    missing_reason: str,
) -> DecisionField:
    if context is None:
        return _missing(missing_reason)
    return _available(str(getattr(context, name)))


def _journal_result(
    snapshot: TradeDecisionSnapshot,
    episode: TradeEpisode,
) -> dict[str, object]:
    return {
        "episode_id": episode.episode_id,
        "decision_snapshot_id": snapshot.snapshot_id,
        "review_triggered": episode.status is not EpisodeStatus.OPEN,
    }


class TradeReviewService:
    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list_episodes(
        self,
        *,
        owner_id: str,
        instrument_id: str | None = None,
        status: str | None = None,
        review_status: str | None = None,
    ) -> tuple[TradeEpisode, ...]:
        statement = (
            select(TradeEpisodeRow)
            .where(TradeEpisodeRow.owner_id == owner_id)
            .order_by(TradeEpisodeRow.updated_at.desc())
        )
        if instrument_id:
            statement = statement.where(TradeEpisodeRow.instrument_id == instrument_id)
        if status:
            statement = statement.where(TradeEpisodeRow.status == status)
        if review_status:
            statement = statement.where(TradeEpisodeRow.review_status == review_status)
        async with self._session_factory() as session:
            rows = (await session.scalars(statement)).all()
        return tuple(TradeEpisode.model_validate(row.payload_json) for row in rows)

    async def get_episode(self, *, owner_id: str, episode_id: str) -> TradeEpisode:
        async with self._session_factory() as session:
            row = await session.get(TradeEpisodeRow, episode_id)
        if row is None or row.owner_id != owner_id:
            raise LookupError("trade episode not found")
        return TradeEpisode.model_validate(row.payload_json)

    async def decisions(
        self, *, owner_id: str, episode_id: str
    ) -> tuple[TradeDecisionSnapshot, ...]:
        await self.get_episode(owner_id=owner_id, episode_id=episode_id)
        async with self._session_factory() as session:
            rows = (
                await session.scalars(
                    select(TradeDecisionSnapshotRow)
                    .where(TradeDecisionSnapshotRow.episode_id == episode_id)
                    .order_by(TradeDecisionSnapshotRow.occurred_at)
                )
            ).all()
        return tuple(
            TradeDecisionSnapshot.model_validate(row.payload_json) for row in rows
        )

    async def get_review(self, *, owner_id: str, episode_id: str) -> TradeReview:
        await self.get_episode(owner_id=owner_id, episode_id=episode_id)
        async with self._session_factory() as session:
            row = await session.scalar(
                select(TradeReviewRow).where(
                    TradeReviewRow.episode_id == episode_id,
                    TradeReviewRow.kind == "final",
                )
            )
        if row is None:
            raise LookupError("trade review not found")
        return TradeReview.model_validate(row.payload_json)

    async def retry_review(self, *, owner_id: str, episode_id: str) -> TradeReview:
        try:
            return await self.get_review(owner_id=owner_id, episode_id=episode_id)
        except LookupError:
            pass
        async with self._session_factory() as session:
            async with session.begin():
                row = await session.scalar(
                    select(TradeEpisodeRow)
                    .where(
                        TradeEpisodeRow.episode_id == episode_id,
                        TradeEpisodeRow.owner_id == owner_id,
                    )
                    .with_for_update()
                )
                if row is None:
                    raise LookupError("trade episode not found")
                episode = TradeEpisode.model_validate(row.payload_json)
                if episode.current_quantity != ZERO:
                    raise ValueError("final review requires a closed position")
                return await self._complete_review(session, episode, datetime.now(UTC))

    async def current_profile_version(self, *, owner_id: str) -> int | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(InvestmentProfile.version)
                .where(InvestmentProfile.user_id == owner_id)
                .order_by(InvestmentProfile.version.desc())
            )

    async def project_execution_outbox(
        self,
        *,
        owner_id: str | None = None,
        fill_ids: frozenset[str] | None = None,
        batch_size: int = 100,
    ) -> tuple[dict[str, object], ...]:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        if fill_ids is not None and not fill_ids:
            return ()
        projected: list[dict[str, object]] = []
        async with self._session_factory() as session:
            statement = (
                select(SimulationExecutionOutboxRow.message_id)
                .where(
                    SimulationExecutionOutboxRow.topic
                    == "simulation.execution.fill_recorded",
                    SimulationExecutionOutboxRow.published_at.is_(None),
                )
                .order_by(SimulationExecutionOutboxRow.occurred_at)
                .limit(batch_size)
            )
            if fill_ids is not None:
                statement = statement.where(
                    SimulationExecutionOutboxRow.aggregate_id.in_(fill_ids)
                )
            elif owner_id is None:
                retry_before = datetime.now(UTC) - _BACKGROUND_RETRY_INTERVAL
                statement = statement.where(
                    or_(
                        SimulationExecutionOutboxRow.last_attempt_at.is_(None),
                        SimulationExecutionOutboxRow.last_attempt_at <= retry_before,
                    )
                )
            message_ids = tuple(
                await session.scalars(statement)
            )
        for message_id in message_ids:
            attempted_at = datetime.now(UTC)
            try:
                async with self._session_factory() as session:
                    async with session.begin():
                        row = await session.scalar(
                            select(SimulationExecutionOutboxRow)
                            .where(
                                SimulationExecutionOutboxRow.message_id == message_id,
                                SimulationExecutionOutboxRow.published_at.is_(None),
                            )
                            .with_for_update(skip_locked=True)
                        )
                        if row is None:
                            continue
                        result = await self._project_outbox_row(
                            session,
                            row,
                            owner_id=owner_id,
                        )
                        if result is None:
                            continue
                        projected.append(result)
                        row.attempt_count += 1
                        row.last_attempt_at = attempted_at
                        row.last_error = None
                        row.published_at = attempted_at
            except Exception as error:
                async with self._session_factory() as session:
                    async with session.begin():
                        await session.execute(
                            update(SimulationExecutionOutboxRow)
                            .where(
                                SimulationExecutionOutboxRow.message_id == message_id,
                                SimulationExecutionOutboxRow.published_at.is_(None),
                            )
                            .values(
                                attempt_count=(
                                    SimulationExecutionOutboxRow.attempt_count + 1
                                ),
                                last_attempt_at=attempted_at,
                                last_error=(f"{type(error).__name__}: {error}")[:2_000],
                            )
                        )
                _LOGGER.exception(
                    "trade review outbox projection failed for %s",
                    message_id,
                )
        return tuple(projected)

    async def _project_outbox_row(
        self,
        session: AsyncSession,
        row: SimulationExecutionOutboxRow,
        *,
        owner_id: str | None,
    ) -> dict[str, object] | None:
        event = await session.get(SimulationExecutionEventRow, row.event_id)
        if event is None:
            raise ValueError("fill outbox references a missing execution event")
        expected_hash = simulation_event_digest(
            {
                "aggregate_type": event.aggregate_type,
                "aggregate_id": event.aggregate_id,
                "sequence": event.sequence,
                "event_type": event.event_type,
                "previous_hash": event.previous_hash,
                "payload": event.payload_json,
            }
        )
        if (
            event.event_type != "fill_recorded"
            or event.aggregate_type != "fill"
            or event.aggregate_id != row.aggregate_id
            or event.event_hash != row.event_hash
            or event.event_hash != expected_hash
            or event.payload_json != row.payload_json
        ):
            raise ValueError("fill outbox does not match its immutable execution event")
        payload = event.payload_json
        event_owner_id = str(payload.get("owner_id", ""))
        if owner_id is not None and event_owner_id != owner_id:
            return None
        draft_payload = payload.get("draft")
        fill_payload = payload.get("fill")
        order_payload = payload.get("order")
        if not event_owner_id:
            raise ValueError("fill outbox is missing its owner")
        if not isinstance(draft_payload, dict):
            raise ValueError("fill outbox is missing its draft fact")
        if not isinstance(fill_payload, dict):
            raise ValueError("fill outbox is missing its fill fact")
        if not isinstance(order_payload, dict):
            raise ValueError("fill outbox is missing its order fact")
        draft = draft_payload.get("draft")
        if not isinstance(draft, dict):
            raise ValueError("fill outbox draft fact is malformed")
        context_payload = order_payload.get("decision_context")
        decision_context = (
            TradeDecisionContext.model_validate(context_payload)
            if context_payload is not None
            else None
        )
        return await self._record_fill_fact(
            session,
            owner_id=event_owner_id,
            account_id=str(draft["account_id"]),
            order_id=str(fill_payload["order_id"]),
            fill_id=str(fill_payload["fill_id"]),
            instrument_id=str(draft["instrument_id"]),
            side=str(draft["side"]),
            quantity=Decimal(str(fill_payload["quantity"])),
            price=Decimal(str(fill_payload["price"])),
            fee=Decimal(str(fill_payload["fee"])),
            occurred_at=_aware_datetime(fill_payload["occurred_at"]),
            market_evidence=dict(fill_payload["market_evidence"]),
            position_quantity_after=None,
            profile_version=order_payload.get("submission_profile_version"),
            decision_context=decision_context,
        )

    async def journal_for_order(
        self,
        *,
        owner_id: str,
        order_id: str,
    ) -> dict[str, object] | None:
        async with self._session_factory() as session:
            snapshot_row = await session.scalar(
                select(TradeDecisionSnapshotRow)
                .where(
                    TradeDecisionSnapshotRow.owner_id == owner_id,
                    TradeDecisionSnapshotRow.order_id == order_id,
                )
                .order_by(TradeDecisionSnapshotRow.occurred_at.desc())
                .limit(1)
            )
            if snapshot_row is None:
                return None
            episode_row = await session.get(
                TradeEpisodeRow,
                snapshot_row.episode_id,
            )
            if episode_row is None:
                raise RuntimeError("trade decision snapshot has no episode")
            snapshot = TradeDecisionSnapshot.model_validate(snapshot_row.payload_json)
            episode = TradeEpisode.model_validate(episode_row.payload_json)
            return _journal_result(snapshot, episode)

    async def record_filled_order(
        self,
        *,
        owner_id: str,
        account_id: str,
        order: object,
        market_evidence: dict[str, str],
        position_quantity_after: Decimal,
        profile_version: int | None,
        decision_context: TradeDecisionContext | None = None,
    ) -> dict[str, object]:
        payload = (
            order.model_dump(mode="json")
            if hasattr(order, "model_dump")
            else dict(order)  # type: ignore[arg-type]
        )
        fills = payload.get("fills") or []
        if not fills:
            raise ValueError("filled order has no execution fill")
        fill = fills[-1]
        async with self._session_factory() as session:
            async with session.begin():
                if profile_version is None:
                    profile_version = await session.scalar(
                        select(InvestmentProfile.version)
                        .where(InvestmentProfile.user_id == owner_id)
                        .order_by(InvestmentProfile.version.desc())
                    )
                return await self._record_fill_fact(
                    session,
                    owner_id=owner_id,
                    account_id=account_id,
                    order_id=str(payload["order_id"]),
                    fill_id=str(fill["fill_id"]),
                    instrument_id=str(payload["instrument_id"]),
                    side=str(payload["side"]),
                    quantity=Decimal(str(fill["quantity"])),
                    price=Decimal(str(fill["price"])),
                    fee=Decimal(str(fill["fee"])),
                    occurred_at=_aware_datetime(fill["occurred_at"]),
                    market_evidence=market_evidence,
                    position_quantity_after=position_quantity_after,
                    profile_version=profile_version,
                    decision_context=decision_context,
                )

    async def _record_fill_fact(
        self,
        session: AsyncSession,
        *,
        owner_id: str,
        account_id: str,
        order_id: str,
        fill_id: str,
        instrument_id: str,
        side: str,
        quantity: Decimal,
        price: Decimal,
        fee: Decimal,
        occurred_at: datetime,
        market_evidence: dict[str, str],
        position_quantity_after: Decimal | None,
        profile_version: object,
        decision_context: TradeDecisionContext | None,
    ) -> dict[str, object]:
        prior = await session.scalar(
            select(TradeDecisionSnapshotRow).where(
                TradeDecisionSnapshotRow.fill_id == fill_id
            )
        )
        if prior is not None:
            snapshot = TradeDecisionSnapshot.model_validate(prior.payload_json)
            episode_row = await session.get(TradeEpisodeRow, prior.episode_id)
            if episode_row is None:
                raise RuntimeError("trade decision snapshot has no episode")
            episode = TradeEpisode.model_validate(episode_row.payload_json)
            return _journal_result(snapshot, episode)

        episode_row = await session.scalar(
            select(TradeEpisodeRow)
            .where(
                TradeEpisodeRow.owner_id == owner_id,
                TradeEpisodeRow.account_id == account_id,
                TradeEpisodeRow.instrument_id == instrument_id,
                TradeEpisodeRow.status == EpisodeStatus.OPEN.value,
            )
            .with_for_update()
        )
        now = occurred_at.astimezone(UTC)
        if episode_row is None:
            if side != "buy":
                raise ValueError("sell fill has no active trade episode")
            next_quantity = (
                position_quantity_after
                if position_quantity_after is not None
                else quantity
            )
            episode = TradeEpisode(
                episode_id=_id("episode"),
                owner_id=owner_id,
                account_id=account_id,
                instrument_id=instrument_id,
                status=EpisodeStatus.OPEN,
                opened_at=now,
                opening_quantity=quantity,
                current_quantity=next_quantity,
                revision=1,
                created_at=now,
                updated_at=now,
            )
            episode_row = TradeEpisodeRow(
                episode_id=episode.episode_id,
                owner_id=owner_id,
                account_id=account_id,
                instrument_id=episode.instrument_id,
                status=episode.status.value,
                review_status=None,
                revision=episode.revision,
                payload_json=episode.model_dump(mode="json"),
                opened_at=now,
                closed_at=None,
                created_at=now,
                updated_at=now,
            )
            session.add(episode_row)
            await session.flush()
        else:
            episode = TradeEpisode.model_validate(episode_row.payload_json)
            expected_revision = episode.revision
            next_quantity = (
                position_quantity_after
                if position_quantity_after is not None
                else _position_after(episode.current_quantity, side, quantity)
            )
            review_triggered = side == "sell" and next_quantity == ZERO
            episode = episode.model_copy(
                update={
                    "status": (
                        EpisodeStatus.CLOSED_PENDING_REVIEW
                        if review_triggered
                        else EpisodeStatus.OPEN
                    ),
                    "review_status": (
                        ReviewStatus.PENDING if review_triggered else None
                    ),
                    "current_quantity": next_quantity,
                    "closed_at": now if review_triggered else None,
                    "revision": episode.revision + 1,
                    "updated_at": now,
                }
            )
            result = await session.execute(
                update(TradeEpisodeRow)
                .where(
                    TradeEpisodeRow.episode_id == episode.episode_id,
                    TradeEpisodeRow.revision == expected_revision,
                )
                .values(
                    status=episode.status.value,
                    review_status=(
                        episode.review_status.value if episode.review_status else None
                    ),
                    revision=episode.revision,
                    payload_json=episode.model_dump(mode="json"),
                    closed_at=episode.closed_at,
                    updated_at=now,
                )
            )
            if result.rowcount != 1:
                raise ConcurrentCommandConflict(
                    "trade episode revision changed during fill projection"
                )

        review_triggered = side == "sell" and episode.current_quantity == ZERO
        normalized_profile_version = (
            int(profile_version) if profile_version is not None else None
        )
        snapshot = TradeDecisionSnapshot(
            snapshot_id=_id("decision"),
            episode_id=episode.episode_id,
            owner_id=owner_id,
            order_id=order_id,
            fill_id=fill_id,
            instrument_id=episode.instrument_id,
            side=side,
            quantity=quantity,
            price=price,
            fee=fee,
            occurred_at=now,
            market_evidence=market_evidence,
            profile_version=normalized_profile_version,
            thesis=_context_field(
                decision_context,
                "thesis",
                "当时没有可持久引用的交易理由",
            ),
            expected_return=_context_field(
                decision_context,
                "expected_return",
                "当时没有可持久引用的预期收益",
            ),
            primary_risks=_context_field(
                decision_context,
                "primary_risks",
                "当时没有可持久引用的主要风险",
            ),
            contrary_evidence=_context_field(
                decision_context,
                "contrary_evidence",
                "当时没有可持久引用的反方证据",
            ),
            expected_holding_period=_context_field(
                decision_context,
                "expected_holding_period",
                "当时没有记录预计持有周期",
            ),
            confidence=_context_field(
                decision_context,
                "confidence",
                "当时没有记录主观信心",
            ),
            created_at=now,
        )
        session.add(
            TradeDecisionSnapshotRow(
                snapshot_id=snapshot.snapshot_id,
                episode_id=episode.episode_id,
                owner_id=owner_id,
                order_id=snapshot.order_id,
                fill_id=snapshot.fill_id,
                occurred_at=now,
                payload_json=snapshot.model_dump(mode="json"),
                created_at=now,
            )
        )
        if review_triggered:
            await self._complete_review(session, episode, now)
        return _journal_result(snapshot, episode)

    async def _complete_review(
        self, session: AsyncSession, episode: TradeEpisode, now: datetime
    ) -> TradeReview:
        rows = (
            await session.scalars(
                select(TradeDecisionSnapshotRow)
                .where(TradeDecisionSnapshotRow.episode_id == episode.episode_id)
                .order_by(TradeDecisionSnapshotRow.occurred_at)
            )
        ).all()
        decisions = [
            TradeDecisionSnapshot.model_validate(row.payload_json) for row in rows
        ]
        buys = sum(
            (
                item.price * item.quantity + item.fee
                for item in decisions
                if item.side == "buy"
            ),
            ZERO,
        )
        sells = sum(
            (
                item.price * item.quantity - item.fee
                for item in decisions
                if item.side == "sell"
            ),
            ZERO,
        )
        pnl = sells - buys
        return_percent = (pnl / buys * Decimal("100")) if buys else None
        opening_decision = next(
            (item for item in decisions if item.side == "buy"),
            decisions[0] if decisions else None,
        )
        context_fields = (
            ("thesis", "交易理由是否成立"),
            ("expected_return", "预期收益与实际结果的偏离"),
            ("primary_risks", "主要风险是否发生"),
            ("contrary_evidence", "反方证据是否被验证"),
            ("expected_holding_period", "预计持有周期与实际周期的偏离"),
            ("confidence", "提交时信心与结果的关系"),
        )
        unknown_points = tuple(
            label
            for field_name, label in context_fields
            if opening_decision is None
            or getattr(opening_decision, field_name).status is Availability.UNAVAILABLE
        )
        expected_return = (
            opening_decision.expected_return.value
            if opening_decision is not None
            and opening_decision.expected_return.status is Availability.AVAILABLE
            else None
        )
        if expected_return is None:
            expected_return_assessment = (
                "提交时未保留可用的预期收益，无法比较预期与实际。"
            )
        elif return_percent is None:
            expected_return_assessment = (
                f"提交时预期收益为“{expected_return}”；本次实际损益为 {pnl} 元。"
            )
        else:
            expected_return_assessment = (
                f"提交时预期收益为“{expected_return}”；"
                f"本次实际收益率为 {return_percent.quantize(Decimal('0.01'))}%。"
            )
        context_complete = not unknown_points
        review_id = _id("review")
        feedback_id = _id("feedback")
        review = TradeReview(
            review_id=review_id,
            episode_id=episode.episode_id,
            owner_id=episode.owner_id,
            status=ReviewStatus.COMPLETED,
            expected_return_assessment=expected_return_assessment,
            actual_return_rmb=pnl,
            actual_return_percent=return_percent,
            holding_period_seconds=max(
                0, int(((episode.closed_at or now) - episode.opened_at).total_seconds())
            ),
            execution_assessment=(
                "成交、仓位与提交时决策上下文完整，复盘可按原始判断逐项核对。"
                if context_complete
                else "成交与仓位事实完整；部分提交时决策上下文不可用，相关结论保持未知。"
            ),
            established_points=(
                ("提交时六项决策上下文已完整留存。",) if context_complete else ()
            ),
            unknown_points=unknown_points,
            next_adjustments=(
                ("后续交易继续按同一口径记录决策上下文，便于跨期比较。",)
                if context_complete
                else ("后续交易应在提交前补齐不可用的决策上下文字段。",)
            ),
            evidence_references=tuple(
                {
                    "object_type": "simulation_fill",
                    "object_id": item.fill_id,
                    "version": "1",
                }
                for item in decisions
            ),
            profile_feedback_id=feedback_id,
            created_at=now,
            completed_at=now,
        )
        session.add(
            TradeReviewRow(
                review_id=review.review_id,
                episode_id=episode.episode_id,
                owner_id=episode.owner_id,
                kind=review.kind,
                status=review.status.value,
                payload_json=review.model_dump(mode="json"),
                created_at=now,
                completed_at=now,
            )
        )
        feedback = await self._create_profile_version(
            session, episode, review, feedback_id, now
        )
        session.add(
            ProfileFeedbackRow(
                feedback_id=feedback.feedback_id,
                owner_id=episode.owner_id,
                episode_id=episode.episode_id,
                review_id=review.review_id,
                payload_json=feedback.model_dump(mode="json"),
                created_at=now,
            )
        )
        completed = episode.model_copy(
            update={
                "status": EpisodeStatus.REVIEW_COMPLETED,
                "review_status": ReviewStatus.COMPLETED,
                "revision": episode.revision + 1,
                "updated_at": now,
            }
        )
        result = await session.execute(
            update(TradeEpisodeRow)
            .where(
                TradeEpisodeRow.episode_id == episode.episode_id,
                TradeEpisodeRow.revision == episode.revision,
            )
            .values(
                status=completed.status.value,
                review_status=ReviewStatus.COMPLETED.value,
                revision=completed.revision,
                payload_json=completed.model_dump(mode="json"),
                updated_at=now,
            )
        )
        if result.rowcount != 1:
            raise ConcurrentCommandConflict(
                "trade episode revision changed during review completion"
            )
        return review

    async def _create_profile_version(
        self,
        session: AsyncSession,
        episode: TradeEpisode,
        review: TradeReview,
        feedback_id: str,
        now: datetime,
    ) -> ProfileFeedback:
        parent = await session.scalar(
            select(InvestmentProfile)
            .where(InvestmentProfile.user_id == episode.owner_id)
            .order_by(InvestmentProfile.version.desc())
        )
        if parent is None:
            return ProfileFeedback(
                feedback_id=feedback_id,
                owner_id=episode.owner_id,
                episode_id=episode.episode_id,
                review_id=review.review_id,
                summary="未找到可继承的用户画像，未创建新画像版本。",
                created_at=now,
            )
        summary = dict(parent.report_summary)
        summary["latest_trade_review"] = {
            "episode_id": episode.episode_id,
            "review_id": review.review_id,
            "actual_return_rmb": str(review.actual_return_rmb),
            "evidence_quality": (
                "decision_context_complete"
                if not review.unknown_points
                else "decision_context_incomplete"
            ),
        }
        child = InvestmentProfile(
            user_id=parent.user_id,
            session_id=None,
            version=parent.version + 1,
            objective_profile=dict(parent.objective_profile),
            dimension_scores=dict(parent.dimension_scores),
            profile_evidence={
                **dict(parent.profile_evidence),
                "trade_review": {
                    "episode_id": episode.episode_id,
                    "review_id": review.review_id,
                },
            },
            archetype_code=parent.archetype_code,
            archetype_title=parent.archetype_title,
            risk_level=parent.risk_level,
            loss_tolerance_percent=parent.loss_tolerance_percent,
            confidence=parent.confidence,
            completeness=parent.completeness,
            education_only=parent.education_only,
            report_summary=summary,
            parent_profile_id=parent.id,
            source_type="trade_review",
            source_id=review.review_id,
        )
        session.add(child)
        await session.flush()
        recommendations = (
            await session.scalars(
                select(DirectionRecommendation)
                .where(DirectionRecommendation.profile_id == parent.id)
                .order_by(DirectionRecommendation.rank)
            )
        ).all()
        session.add_all(
            [
                DirectionRecommendation(
                    profile_id=child.id,
                    direction=item.direction,
                    score=item.score,
                    rank=item.rank,
                    reason=item.reason,
                    actionable=item.actionable,
                    selected=item.selected,
                    selected_at=item.selected_at,
                )
                for item in recommendations
            ]
        )
        return ProfileFeedback(
            feedback_id=feedback_id,
            owner_id=episode.owner_id,
            episode_id=episode.episode_id,
            review_id=review.review_id,
            parent_profile_version=parent.version,
            new_profile_version=child.version,
            summary=(
                "决策上下文完整；已创建审计版本，画像维度保持不变。"
                if not review.unknown_points
                else "部分决策上下文不可用；已创建审计版本，画像维度保持不变。"
            ),
            created_at=now,
        )
