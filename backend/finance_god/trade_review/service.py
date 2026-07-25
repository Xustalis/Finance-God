from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.profile import DirectionRecommendation, InvestmentProfile
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


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:20]}"


def _missing(reason: str) -> DecisionField:
    return DecisionField(
        status=Availability.UNAVAILABLE,
        unavailable_reason=reason,
    )


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
            statement = statement.where(
                TradeEpisodeRow.instrument_id == instrument_id
            )
        if status:
            statement = statement.where(TradeEpisodeRow.status == status)
        if review_status:
            statement = statement.where(
                TradeEpisodeRow.review_status == review_status
            )
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

    async def retry_review(
        self, *, owner_id: str, episode_id: str
    ) -> TradeReview:
        episode = await self.get_episode(owner_id=owner_id, episode_id=episode_id)
        try:
            return await self.get_review(owner_id=owner_id, episode_id=episode_id)
        except LookupError:
            pass
        if episode.current_quantity != ZERO:
            raise ValueError("final review requires a closed position")
        async with self._session_factory() as session:
            async with session.begin():
                return await self._complete_review(session, episode, datetime.now(UTC))

    async def record_filled_order(
        self,
        *,
        owner_id: str,
        account_id: str,
        order: object,
        market_evidence: dict[str, str],
        position_quantity_after: Decimal,
        profile_version: int | None,
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
        side = str(payload["side"])
        occurred_at = datetime.fromisoformat(str(fill["occurred_at"]))
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=UTC)
        async with self._session_factory() as session:
            async with session.begin():
                if profile_version is None:
                    profile_version = await session.scalar(
                        select(InvestmentProfile.version)
                        .where(InvestmentProfile.user_id == owner_id)
                        .order_by(InvestmentProfile.version.desc())
                    )
                prior = await session.scalar(
                    select(TradeDecisionSnapshotRow).where(
                        TradeDecisionSnapshotRow.fill_id == str(fill["fill_id"])
                    )
                )
                if prior is not None:
                    snapshot = TradeDecisionSnapshot.model_validate(prior.payload_json)
                    episode_row = await session.get(TradeEpisodeRow, prior.episode_id)
                    assert episode_row is not None
                    episode = TradeEpisode.model_validate(episode_row.payload_json)
                    return {
                        "episode_id": episode.episode_id,
                        "decision_snapshot_id": snapshot.snapshot_id,
                        "review_triggered": episode.status
                        is EpisodeStatus.CLOSED_PENDING_REVIEW,
                    }

                episode_row = await session.scalar(
                    select(TradeEpisodeRow).where(
                        TradeEpisodeRow.owner_id == owner_id,
                        TradeEpisodeRow.account_id == account_id,
                        TradeEpisodeRow.instrument_id == str(payload["instrument_id"]),
                        TradeEpisodeRow.status == EpisodeStatus.OPEN.value,
                    )
                )
                now = occurred_at.astimezone(UTC)
                if episode_row is None:
                    if side != "buy":
                        raise ValueError("sell fill has no active trade episode")
                    episode = TradeEpisode(
                        episode_id=_id("episode"),
                        owner_id=owner_id,
                        account_id=account_id,
                        instrument_id=str(payload["instrument_id"]),
                        status=EpisodeStatus.OPEN,
                        opened_at=now,
                        opening_quantity=Decimal(str(fill["quantity"])),
                        current_quantity=position_quantity_after,
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
                else:
                    episode = TradeEpisode.model_validate(episode_row.payload_json)

                review_triggered = side == "sell" and position_quantity_after == ZERO
                next_status = (
                    EpisodeStatus.CLOSED_PENDING_REVIEW
                    if review_triggered
                    else EpisodeStatus.OPEN
                )
                episode = episode.model_copy(
                    update={
                        "status": next_status,
                        "review_status": (
                            ReviewStatus.PENDING if review_triggered else None
                        ),
                        "current_quantity": position_quantity_after,
                        "closed_at": now if review_triggered else None,
                        "revision": episode.revision + (0 if episode.revision == 1 and side == "buy" else 1),
                        "updated_at": now,
                    }
                )
                episode_row.status = episode.status.value
                episode_row.review_status = (
                    episode.review_status.value if episode.review_status else None
                )
                episode_row.revision = episode.revision
                episode_row.payload_json = episode.model_dump(mode="json")
                episode_row.closed_at = episode.closed_at
                episode_row.updated_at = now

                snapshot = TradeDecisionSnapshot(
                    snapshot_id=_id("decision"),
                    episode_id=episode.episode_id,
                    owner_id=owner_id,
                    order_id=str(payload["order_id"]),
                    fill_id=str(fill["fill_id"]),
                    instrument_id=episode.instrument_id,
                    side=side,
                    quantity=Decimal(str(fill["quantity"])),
                    price=Decimal(str(fill["price"])),
                    fee=Decimal(str(fill["fee"])),
                    occurred_at=now,
                    market_evidence=market_evidence,
                    profile_version=profile_version,
                    thesis=_missing("当时没有可持久引用的交易理由"),
                    expected_return=_missing("当时没有可持久引用的预期收益"),
                    primary_risks=_missing("当时没有可持久引用的主要风险"),
                    contrary_evidence=_missing("当时没有可持久引用的反方证据"),
                    expected_holding_period=_missing("当时没有记录预计持有周期"),
                    confidence=_missing("当时没有记录主观信心"),
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
            return {
                "episode_id": episode.episode_id,
                "decision_snapshot_id": snapshot.snapshot_id,
                "review_triggered": review_triggered,
            }

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
        decisions = [TradeDecisionSnapshot.model_validate(row.payload_json) for row in rows]
        buys = sum(
            (item.price * item.quantity + item.fee for item in decisions if item.side == "buy"),
            ZERO,
        )
        sells = sum(
            (item.price * item.quantity - item.fee for item in decisions if item.side == "sell"),
            ZERO,
        )
        pnl = sells - buys
        return_percent = (pnl / buys * Decimal("100")) if buys else None
        review_id = _id("review")
        feedback_id = _id("feedback")
        review = TradeReview(
            review_id=review_id,
            episode_id=episode.episode_id,
            owner_id=episode.owner_id,
            status=ReviewStatus.COMPLETED,
            expected_return_assessment="原交易未记录预期收益，无法比较预期与实际。",
            actual_return_rmb=pnl,
            actual_return_percent=return_percent,
            holding_period_seconds=max(
                0, int(((episode.closed_at or now) - episode.opened_at).total_seconds())
            ),
            execution_assessment=(
                "成交与仓位事实完整；原计划价格、数量和退出纪律未记录，无法评价计划偏离。"
            ),
            unknown_points=(
                "交易理由是否成立",
                "主要风险与反方证据是否被验证",
                "预计持有周期与实际周期的偏离",
            ),
            next_adjustments=("后续交易如需更完整复盘，应从可持久引用的交易计划发起。",),
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
        row = await session.get(TradeEpisodeRow, episode.episode_id)
        assert row is not None
        row.status = completed.status.value
        row.review_status = ReviewStatus.COMPLETED.value
        row.revision = completed.revision
        row.payload_json = completed.model_dump(mode="json")
        row.updated_at = now
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
            "evidence_quality": "insufficient_subjective_context",
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
            summary="主观决策证据不足；已创建审计版本，画像维度保持不变。",
            created_at=now,
        )
