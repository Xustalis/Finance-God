"""Versioned TradePlan application service and T04 page contract."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from finance_god.application.candidate_service import CandidateResponse
from finance_god.application.portfolio_query import PortfolioPosition, PortfolioView
from finance_god.domain import (
    AuditReference,
    ConcurrentCommandConflict,
    DomainInvariantViolation,
    OrderSide,
    OrderType,
    TimeInForce,
    TradePlan,
    TradePlanAction,
    TradePlanStatus,
    VersionReference,
)
from finance_god.execution import DraftMode, StoredDraft
from finance_god.execution.matcher import SimulationRuleSet
from finance_god.infrastructure.persistence.trade_plan_repository import (
    StoredTradePlan,
    TradePlanDraftLink,
)
from finance_god.infrastructure.persistence.trade_plan_uow import TradePlanUnitOfWork
from finance_god.market_data.service import MarketQuote, QuoteBatch
from finance_god.trading.rules_v1 import HARD_SINGLE_ASSET_RATIO

PLAN_TTL = timedelta(minutes=30)
QUANTITY_QUANTUM = Decimal("0.00000001")
ZERO = Decimal("0")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TradePlanActionRevision(StrictModel):
    action_id: str = Field(min_length=1, max_length=160)
    quantity: Decimal | None = Field(default=None, gt=0)
    included: bool = True


class TradePlanCapability(StrictModel):
    action: str
    enabled: bool
    reason_code: str | None = None
    reason: str | None = None


class TradePlanWarning(StrictModel):
    code: str
    severity: str = Field(pattern=r"^(info|warning|blocking)$")
    message: str
    affected_fields: tuple[str, ...] = ()


class TradePlanDataStatus(StrictModel):
    provider: str
    provider_time: str | None
    frequency: str | None
    freshness: str = Field(pattern=r"^(fresh|delayed|stale|unknown)$")
    last_success_at: str | None


class TradePlanVersionSummary(StrictModel):
    revision: int
    status: TradePlanStatus
    recorded_at: datetime
    actor_id: str


class TradePlanPageView(StrictModel):
    object: TradePlan
    source_type: str
    source_id: str
    version: str
    generated_at: datetime
    data_status: TradePlanDataStatus
    capabilities: tuple[TradePlanCapability, ...]
    warnings: tuple[TradePlanWarning, ...]
    draft_links: tuple[TradePlanDraftLink, ...]
    history: tuple[TradePlanVersionSummary, ...]


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdGenerator(Protocol):
    def new_id(self, prefix: str) -> str: ...


class CandidateReader(Protocol):
    async def candidates(
        self, *, owner_id: str, now: datetime, ignored: dict[str, str] | None = None
    ) -> CandidateResponse: ...


class PortfolioReader(Protocol):
    async def positions(self, *, owner_id: str) -> PortfolioView: ...


class DraftCreator(Protocol):
    async def create_order_draft(self, **kwargs: Any) -> StoredDraft: ...


QuotesProvider = Callable[[list[str]], Awaitable[QuoteBatch]]


class TradePlanService:
    def __init__(
        self,
        *,
        session_factory: Callable[[], AsyncSession],
        clock: Clock,
        ids: IdGenerator,
        candidates: CandidateReader,
        portfolio: PortfolioReader,
        quotes_provider: QuotesProvider,
        drafts: DraftCreator,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._ids = ids
        self._candidates = candidates
        self._portfolio = portfolio
        self._quotes = quotes_provider
        self._drafts = drafts
        self._rules = SimulationRuleSet()

    async def create_from_candidate(
        self, *, owner_id: str, instrument_id: str, idempotency_key: str
    ) -> TradePlanPageView:
        existing = await self._by_creation_key(owner_id, idempotency_key)
        if existing is not None:
            if existing.source_type != "candidate" or existing.source_id != instrument_id:
                raise ConcurrentCommandConflict(
                    "idempotency key was already used for another trade plan source"
                )
            return await self._view(existing)
        now = self._clock.now()
        response = await self._candidates.candidates(owner_id=owner_id, now=now)
        candidate = next(
            (
                item
                for item in getattr(response, "candidates", ())
                if item.instrument_id == instrument_id
            ),
            None,
        )
        if candidate is None:
            raise LookupError("candidate not found")
        if not candidate.tradable or candidate.ignored:
            raise DomainInvariantViolation(
                "candidate is not eligible to create a trade plan"
            )
        portfolio = await self._portfolio.positions(owner_id=owner_id)
        quote = await self._require_quotes([instrument_id])
        action = TradePlanAction(
            action_id=self._ids.new_id("plan-action"),
            instrument_id=instrument_id,
            side="buy",
            quantity=None,
            reference_price=quote[instrument_id].last,
            rationale=candidate.purpose,
        )
        inputs = (
            VersionReference(
                object_type="candidate_rule_set",
                object_id="candidate_scoring",
                version=response.rule_version,
            ),
            VersionReference(
                object_type="portfolio_snapshot",
                object_id=portfolio.account_id,
                version=portfolio.as_of.isoformat(),
            ),
            _quote_reference(quote[instrument_id]),
        )
        stored = self._new_plan(
            owner_id=owner_id,
            account_id=portfolio.account_id,
            source_type="candidate",
            source_id=instrument_id,
            purpose=candidate.purpose,
            actions=(action,),
            inputs=inputs,
            disagreements=tuple(item.detail for item in candidate.exclusions),
            quotes=quote,
            now=now,
        )
        await self._insert(stored, creation_key=idempotency_key)
        return await self._view(stored)

    async def create_from_portfolio_deviation(
        self, *, owner_id: str, idempotency_key: str
    ) -> TradePlanPageView:
        existing = await self._by_creation_key(owner_id, idempotency_key)
        if existing is not None:
            if existing.source_type != "portfolio_deviation":
                raise ConcurrentCommandConflict(
                    "idempotency key was already used for another trade plan source"
                )
            return await self._view(existing)
        now = self._clock.now()
        portfolio = await self._portfolio.positions(owner_id=owner_id)
        total_cost = sum((row.cost_basis_rmb for row in portfolio.positions), ZERO)
        if total_cost <= ZERO:
            raise DomainInvariantViolation(
                "portfolio has no cost basis for deviation calculation"
            )
        proposals: list[tuple[PortfolioPosition, Decimal]] = []
        for position in portfolio.positions:
            weight = position.cost_basis_rmb / total_cost
            if weight <= HARD_SINGLE_ASSET_RATIO or position.available_quantity <= ZERO:
                continue
            quantity = (
                position.quantity
                * (weight - HARD_SINGLE_ASSET_RATIO)
                / weight
            ).quantize(QUANTITY_QUANTUM, rounding=ROUND_DOWN)
            quantity = min(quantity, position.available_quantity)
            if quantity > ZERO:
                proposals.append((position, quantity))
        if not proposals:
            raise DomainInvariantViolation(
                "portfolio has no actionable single-asset concentration deviation"
            )
        symbols = [position.instrument_id for position, _ in proposals]
        quotes = await self._require_quotes(symbols)
        actions = tuple(
            TradePlanAction(
                action_id=self._ids.new_id("plan-action"),
                instrument_id=position.instrument_id,
                side="sell",
                quantity=quantity,
                reference_price=quotes[position.instrument_id].last,
                rationale=(
                    "按风险规则将单一资产成本占比降至不高于 "
                    f"{HARD_SINGLE_ASSET_RATIO * 100:.0f}% 的建议数量。"
                ),
            )
            for position, quantity in proposals
        )
        inputs = (
            VersionReference(
                object_type="portfolio_snapshot",
                object_id=portfolio.account_id,
                version=portfolio.as_of.isoformat(),
            ),
            VersionReference(
                object_type="risk_rule_set",
                object_id="pre_submit",
                version="risk-rules-v1",
            ),
            *tuple(_quote_reference(quotes[symbol]) for symbol in symbols),
        )
        stored = self._new_plan(
            owner_id=owner_id,
            account_id=portfolio.account_id,
            source_type="portfolio_deviation",
            source_id=portfolio.account_id,
            purpose="降低超过确定性风险阈值的单一资产集中度。",
            actions=actions,
            inputs=inputs,
            disagreements=(),
            quotes=quotes,
            now=now,
        )
        await self._insert(stored, creation_key=idempotency_key)
        return await self._view(stored)

    async def get(self, *, owner_id: str, plan_id: str) -> TradePlanPageView:
        stored = await self._require_latest(owner_id, plan_id)
        return await self._view(stored)

    async def revise(
        self,
        *,
        owner_id: str,
        plan_id: str,
        expected_revision: int,
        actions: tuple[TradePlanActionRevision, ...],
    ) -> TradePlanPageView:
        stored = await self._require_latest(owner_id, plan_id)
        if stored.plan.revision != expected_revision:
            raise ConcurrentCommandConflict(
                "trade plan has changed since it was loaded"
            )
        requested = {item.action_id: item for item in actions}
        if set(requested) != {item.action_id for item in stored.plan.actions}:
            raise DomainInvariantViolation(
                "trade plan revision must include every existing action"
            )
        included_symbols = [
            action.instrument_id
            for action in stored.plan.actions
            if requested[action.action_id].included
        ]
        quotes = await self._require_quotes(included_symbols) if included_symbols else {}
        revised_actions = tuple(
            action.model_copy(
                update={
                    "quantity": requested[action.action_id].quantity,
                    "included": requested[action.action_id].included,
                    "reference_price": (
                        quotes[action.instrument_id].last
                        if requested[action.action_id].included
                        else action.reference_price
                    ),
                }
            )
            for action in stored.plan.actions
        )
        input_versions = tuple(
            reference
            for reference in stored.plan.input_versions
            if reference.object_type != "market_quote"
        ) + tuple(_quote_reference(quote) for quote in quotes.values())
        now = self._clock.now()
        revised = stored.plan.revise(
            actions=revised_actions,
            input_versions=input_versions,
            estimated_fee_rmb=_estimated_fee(revised_actions, self._rules),
            portfolio_impact=_portfolio_impact(revised_actions, self._rules),
            audit_reference=self._audit(owner_id, now),
        )
        next_stored = StoredTradePlan(
            owner_user_id=owner_id,
            source_type=stored.source_type,
            source_id=stored.source_id,
            plan=revised,
            data_status=_data_status(
                quotes,
                now,
                previous_status=stored.data_status,
            ),
        )
        await self._insert(next_stored)
        return await self._view(next_stored)

    async def confirm_and_generate(
        self,
        *,
        owner_id: str,
        plan_id: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> TradePlanPageView:
        stored = await self._require_latest(owner_id, plan_id)
        plan = stored.plan
        if plan.revision != expected_revision:
            raise ConcurrentCommandConflict(
                "trade plan has changed since it was loaded"
            )
        reason = _confirmation_block(plan, stored.data_status, self._clock.now())
        if reason is not None:
            raise DomainInvariantViolation(reason)
        if plan.status is TradePlanStatus.PENDING_REVIEW:
            confirmed = plan.transition(
                TradePlanStatus.CONFIRMED,
                audit_reference=self._audit(owner_id, self._clock.now()),
            )
            stored = StoredTradePlan(
                owner_user_id=stored.owner_user_id,
                source_type=stored.source_type,
                source_id=stored.source_id,
                plan=confirmed,
                data_status=stored.data_status,
            )
            await self._insert(stored)
            plan = confirmed
        elif plan.status is not TradePlanStatus.CONFIRMED:
            raise DomainInvariantViolation("trade plan cannot generate drafts")

        existing_links = {
            link.action_id: link
            for link in await self._draft_links(plan.plan_id, plan.revision)
        }
        plan_reference = VersionReference(
            object_type="trade_plan",
            object_id=plan.plan_id,
            version=str(plan.revision),
        )
        for action in plan.actions:
            if not action.included or action.action_id in existing_links:
                continue
            created = await self._drafts.create_order_draft(
                owner_id=owner_id,
                mode=DraftMode.PLANNED,
                account_id=plan.account_id,
                instrument_id=action.instrument_id,
                side=OrderSide(action.side),
                order_type=OrderType(action.order_type),
                quantity=action.quantity,
                amount=None,
                limit_price=action.limit_price,
                time_in_force=TimeInForce(action.time_in_force),
                fund_rule_version=None,
                valid_until=plan.expires_at,
                input_versions=plan.input_versions + (plan_reference,),
                plan_reference=plan_reference,
                idempotency_key=f"{idempotency_key}:{action.action_id}",
                request_hash=_request_hash(plan_reference, action),
                reference_price=action.reference_price,
            )
            await self._link_draft(
                plan=plan,
                action_id=action.action_id,
                draft_id=created.draft.draft_id,
                draft_revision=created.draft.revision,
            )
        return await self._view(stored)

    def _new_plan(
        self,
        *,
        owner_id: str,
        account_id: str,
        source_type: str,
        source_id: str,
        purpose: str,
        actions: tuple[TradePlanAction, ...],
        inputs: tuple[VersionReference, ...],
        disagreements: tuple[str, ...],
        quotes: dict[str, MarketQuote],
        now: datetime,
    ) -> StoredTradePlan:
        plan = TradePlan(
            plan_id=self._ids.new_id("trade-plan"),
            account_id=account_id,
            revision=1,
            status=TradePlanStatus.PENDING_REVIEW,
            purpose=purpose,
            actions=actions,
            estimated_fee_rmb=_estimated_fee(actions, self._rules),
            portfolio_impact=_portfolio_impact(actions, self._rules),
            disagreements=disagreements,
            workflow_dependencies=(),
            expires_at=now + PLAN_TTL,
            input_versions=inputs,
            audit_reference=self._audit(owner_id, now),
        )
        return StoredTradePlan(
            owner_user_id=owner_id,
            source_type=source_type,
            source_id=source_id,
            plan=plan,
            data_status=_data_status(quotes, now),
        )

    def _audit(self, actor_id: str, now: datetime) -> AuditReference:
        return AuditReference(
            audit_id=self._ids.new_id("audit"),
            actor_id=actor_id,
            recorded_at=now,
        )

    async def _require_quotes(self, symbols: list[str]) -> dict[str, MarketQuote]:
        batch = await self._quotes(symbols)
        quotes = {quote.symbol: quote for quote in batch.quotes}
        missing = [symbol for symbol in symbols if symbol not in quotes]
        if missing:
            raise DomainInvariantViolation(
                "PandaData quote is unavailable for: " + ", ".join(missing)
            )
        return quotes

    async def _insert(
        self, stored: StoredTradePlan, *, creation_key: str | None = None
    ) -> None:
        async with TradePlanUnitOfWork(self._session_factory) as uow:
            await uow.plans.insert(stored, creation_key=creation_key)
            await uow.commit()

    async def _by_creation_key(
        self, owner_id: str, key: str
    ) -> StoredTradePlan | None:
        async with TradePlanUnitOfWork(self._session_factory) as uow:
            return await uow.plans.get_by_creation_key(owner_id, key)

    async def _require_latest(
        self, owner_id: str, plan_id: str
    ) -> StoredTradePlan:
        async with TradePlanUnitOfWork(self._session_factory) as uow:
            stored = await uow.plans.get_latest(owner_id, plan_id)
        if stored is None:
            raise LookupError("trade plan not found")
        return stored

    async def _draft_links(
        self, plan_id: str, revision: int
    ) -> tuple[TradePlanDraftLink, ...]:
        async with TradePlanUnitOfWork(self._session_factory) as uow:
            return await uow.plans.list_draft_links(plan_id, revision)

    async def _link_draft(
        self,
        *,
        plan: TradePlan,
        action_id: str,
        draft_id: str,
        draft_revision: int,
    ) -> None:
        async with TradePlanUnitOfWork(self._session_factory) as uow:
            await uow.plans.add_draft_link(
                plan_id=plan.plan_id,
                plan_revision=plan.revision,
                action_id=action_id,
                draft_id=draft_id,
                draft_revision=draft_revision,
                created_at=self._clock.now(),
            )
            await uow.commit()

    async def _view(self, stored: StoredTradePlan) -> TradePlanPageView:
        history: list[StoredTradePlan]
        async with TradePlanUnitOfWork(self._session_factory) as uow:
            history = await uow.plans.history(
                stored.owner_user_id, stored.plan.plan_id
            )
            links = await uow.plans.list_draft_links(
                stored.plan.plan_id, stored.plan.revision
            )
        now = self._clock.now()
        block_reason = _confirmation_block(stored.plan, stored.data_status, now)
        included_actions = tuple(
            action for action in stored.plan.actions if action.included
        )
        if (
            stored.plan.status is TradePlanStatus.CONFIRMED
            and len(links) >= len(included_actions)
        ):
            block_reason = "当前已确认版本的订单草稿已经生成。"
        return TradePlanPageView(
            object=stored.plan,
            source_type=stored.source_type,
            source_id=stored.source_id,
            version=str(stored.plan.revision),
            generated_at=now,
            data_status=TradePlanDataStatus.model_validate(stored.data_status),
            capabilities=(
                TradePlanCapability(
                    action="save_version",
                    enabled=stored.plan.status
                    in {TradePlanStatus.DRAFT, TradePlanStatus.PENDING_REVIEW}
                    and now < stored.plan.expires_at,
                    reason_code=None
                    if stored.plan.status
                    in {TradePlanStatus.DRAFT, TradePlanStatus.PENDING_REVIEW}
                    and now < stored.plan.expires_at
                    else "PLAN_NOT_EDITABLE",
                    reason=None
                    if stored.plan.status
                    in {TradePlanStatus.DRAFT, TradePlanStatus.PENDING_REVIEW}
                    and now < stored.plan.expires_at
                    else "当前计划版本不可编辑。",
                ),
                TradePlanCapability(
                    action="confirm_and_generate",
                    enabled=block_reason is None,
                    reason_code=None if block_reason is None else "PLAN_BLOCKED",
                    reason=block_reason,
                ),
            ),
            warnings=_warnings(stored.plan, stored.data_status, now),
            draft_links=links,
            history=tuple(
                TradePlanVersionSummary(
                    revision=item.plan.revision,
                    status=item.plan.status,
                    recorded_at=item.plan.audit_reference.recorded_at,
                    actor_id=item.plan.audit_reference.actor_id,
                )
                for item in history
            ),
        )


def _quote_reference(quote: MarketQuote) -> VersionReference:
    return VersionReference(
        object_type="market_quote",
        object_id=quote.symbol,
        version=quote.provider_time,
    )


def _estimated_fee(
    actions: tuple[TradePlanAction, ...], rules: SimulationRuleSet
) -> Decimal:
    fee = sum(
        (
            action.reference_price
            * action.quantity
            * rules.fee_bps
            / Decimal("10000")
            for action in actions
            if action.included
            and action.reference_price is not None
            and action.quantity is not None
        ),
        ZERO,
    )
    return fee.quantize(Decimal("0.01"))


def _portfolio_impact(
    actions: tuple[TradePlanAction, ...], rules: SimulationRuleSet
) -> str:
    included = [action for action in actions if action.included]
    if not included:
        return "当前版本没有纳入执行的动作。"
    if any(
        action.quantity is None or action.reference_price is None
        for action in included
    ):
        return "补全全部纳入动作的数量后，后端将计算现金与费用影响。"
    cash_change = ZERO
    for action in included:
        reference_price = action.reference_price
        quantity = action.quantity
        if reference_price is None or quantity is None:
            raise RuntimeError("complete trade plan action lost required values")
        notional = reference_price * quantity
        cash_change += -notional if action.side == "buy" else notional
    fee = _estimated_fee(tuple(included), rules)
    cash_change -= fee
    return (
        f"计划包含 {len(included)} 个动作；按当前 PandaData 参考价估算，"
        f"仿真现金变化约为 {cash_change.quantize(Decimal('0.01'))} 元，"
        f"费用约为 {fee} 元。"
    )


def _data_status(
    quotes: dict[str, MarketQuote],
    now: datetime,
    *,
    previous_status: dict[str, object] | None = None,
) -> dict[str, object]:
    if not quotes:
        return previous_status or {
            "provider": "PandaData",
            "provider_time": None,
            "frequency": None,
            "freshness": "unknown",
            "last_success_at": None,
        }
    values = list(quotes.values())
    provider_times = [quote.provider_time for quote in values]
    raw_freshness = {quote.freshness for quote in values}
    freshness = (
        "stale"
        if "stale" in raw_freshness
        else "unknown"
        if "unknown" in raw_freshness
        else "delayed"
        if "not_released" in raw_freshness
        else "fresh"
    )
    frequencies = {quote.frequency for quote in values}
    return {
        "provider": "PandaData",
        "provider_time": min(provider_times),
        "frequency": next(iter(frequencies)) if len(frequencies) == 1 else "mixed",
        "freshness": freshness,
        "last_success_at": now.isoformat(),
    }


def _confirmation_block(
    plan: TradePlan, data_status: dict[str, object], now: datetime
) -> str | None:
    if plan.status is TradePlanStatus.CONFIRMED:
        if now >= plan.expires_at:
            return "计划已过期，不能继续生成草稿。"
        return None
    if plan.status is not TradePlanStatus.PENDING_REVIEW:
        return "当前计划状态不能确认。"
    if now >= plan.expires_at:
        return "计划已过期，请基于最新输入创建新计划。"
    if data_status.get("freshness") in {"stale", "unknown"}:
        return "PandaData 参考价已过期或未知，请刷新计划版本。"
    included = [action for action in plan.actions if action.included]
    if not included:
        return "至少保留一个计划动作。"
    if any(
        action.quantity is None or action.reference_price is None
        for action in included
    ):
        return "请补全全部纳入动作的数量并保存新版本。"
    return None


def _warnings(
    plan: TradePlan, data_status: dict[str, object], now: datetime
) -> tuple[TradePlanWarning, ...]:
    warnings: list[TradePlanWarning] = []
    if now >= plan.expires_at:
        warnings.append(
            TradePlanWarning(
                code="PLAN_EXPIRED",
                severity="blocking",
                message="计划已过期，旧版本仍保留但不能生成草稿。",
                affected_fields=("expires_at",),
            )
        )
    if any(action.included and action.quantity is None for action in plan.actions):
        warnings.append(
            TradePlanWarning(
                code="ACTION_QUANTITY_REQUIRED",
                severity="blocking",
                message="至少一个纳入动作尚未填写数量。",
                affected_fields=("actions.quantity",),
            )
        )
    if data_status.get("freshness") in {"stale", "unknown"}:
        warnings.append(
            TradePlanWarning(
                code="MARKET_DATA_NOT_FRESH",
                severity="blocking",
                message="PandaData 参考价已过期或未知。",
                affected_fields=("data_status",),
            )
        )
    return tuple(warnings)


def _request_hash(
    plan_reference: VersionReference, action: TradePlanAction
) -> str:
    payload = {
        "plan_reference": plan_reference.model_dump(mode="json"),
        "action": action.model_dump(mode="json"),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
