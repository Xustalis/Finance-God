from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from datetime import datetime, timedelta
from decimal import Decimal
from functools import wraps
from types import TracebackType
from typing import ParamSpec, Protocol, Self, TypeVar

from finance_god.domain import (
    AuditReference,
    ExchangeOrder,
    ExchangeOrderStatus,
    OrderDraft,
    OrderDraftStatus,
    OrderSide,
    OrderType,
    RiskCheckResult,
    RiskCheckStatus,
    TimeInForce,
    VersionReference,
)

from .contracts import (
    AccountOwnershipPort,
    BarProvider,
    Clock,
    CostEstimate,
    DraftMode,
    ExecutionFailure,
    ExecutionFailureCode,
    ExecutionRepositoryPort,
    IdGenerator,
    LedgerExecutionPort,
    ManualReviewPort,
    OrderTimelineEntry,
    SimulationFill,
    StoredDraft,
    StoredOrder,
    StoredOrderView,
    SubmissionOutcome,
    SubmissionStatus,
    SubmissionTransport,
    TradePlanPort,
    TrustedRiskPort,
)
from .matcher import DeterministicMatcher

P = ParamSpec("P")
R = TypeVar("R")


class ExecutionUnitOfWork(Protocol):
    repository: ExecutionRepositoryPort

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...


ExecutionUnitOfWorkFactory = Callable[[], ExecutionUnitOfWork]


def _transactional(
    *,
    commit: bool,
) -> Callable[
    [Callable[P, Awaitable[R]]],
    Callable[P, Awaitable[R]],
]:
    def decorate(
        method: Callable[P, Awaitable[R]],
    ) -> Callable[P, Awaitable[R]]:
        @wraps(method)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            service = args[0]
            if not isinstance(service, SimulationExecutionService):
                raise TypeError("transactional method requires execution service")
            if service._active_repository.get() is not None:
                return await method(*args, **kwargs)
            async with service._uow_factory() as uow:
                token = service._active_repository.set(uow.repository)
                try:
                    result = await method(*args, **kwargs)
                    if commit:
                        await uow.commit()
                    return result
                finally:
                    service._active_repository.reset(token)

        return wrapped

    return decorate


class SimulationExecutionService:
    """Simulation-only application service.

    It accepts no broker endpoint, live-trading flag or client-supplied risk
    decision. Formal risk and account ownership are injected trusted providers.
    """

    def __init__(
        self,
        *,
        uow_factory: ExecutionUnitOfWorkFactory,
        accounts: AccountOwnershipPort,
        plans: TradePlanPort,
        manual_review: ManualReviewPort,
        risk: TrustedRiskPort,
        transport: SubmissionTransport,
        bars: BarProvider,
        ledger: LedgerExecutionPort,
        matcher: DeterministicMatcher,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._uow_factory = uow_factory
        self._active_repository: ContextVar[
            ExecutionRepositoryPort | None
        ] = ContextVar("simulation_execution_repository", default=None)
        self._accounts = accounts
        self._plans = plans
        self._manual_review = manual_review
        self._risk = risk
        self._transport = transport
        self._bars = bars
        self._ledger = ledger
        self._matcher = matcher
        self._clock = clock
        self._ids = ids

    @property
    def _repository(self) -> ExecutionRepositoryPort:
        repository = self._active_repository.get()
        if repository is None:
            raise RuntimeError("simulation repository used outside transaction")
        return repository

    @_transactional(commit=True)
    async def create_draft(
        self,
        *,
        owner_id: str,
        mode: DraftMode,
        draft: OrderDraft,
        plan_reference: VersionReference | None,
        idempotency_key: str,
        request_hash: str,
        reference_price: Decimal | None = None,
    ) -> StoredDraft:
        await self._accounts.require_current_account(owner_id, draft.account_id)
        if mode is DraftMode.PLANNED:
            if plan_reference is None:
                raise ValueError("planned draft requires TradePlan reference")
            if plan_reference.object_type != "trade_plan":
                raise ValueError("planned draft dependency must be a TradePlan")
            await self._plans.require_executable(plan_reference)
        stored = StoredDraft(
            owner_id=owner_id,
            mode=mode,
            draft=draft,
            plan_reference=plan_reference,
            reference_price=reference_price,
        )
        return await self._repository.create_draft(
            stored,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

    @_transactional(commit=True)
    async def create_order_draft(
        self,
        *,
        owner_id: str,
        mode: DraftMode,
        account_id: str,
        instrument_id: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal | None,
        amount: Decimal | None,
        limit_price: Decimal | None,
        time_in_force: TimeInForce | None,
        fund_rule_version: VersionReference | None,
        valid_until: datetime,
        input_versions: tuple[VersionReference, ...],
        plan_reference: VersionReference | None,
        idempotency_key: str,
        request_hash: str,
        reference_price: Decimal | None = None,
    ) -> StoredDraft:
        now = self._clock.now()
        draft = OrderDraft.model_validate(
            {
                "draft_id": self._ids.new_id("draft"),
                "revision": 1,
                "status": OrderDraftStatus.DRAFT,
                "account_id": account_id,
                "instrument_id": instrument_id,
                "side": side,
                "order_type": order_type,
                "quantity": quantity,
                "amount": amount,
                "limit_price": limit_price,
                "time_in_force": time_in_force,
                "fund_rule_version": fund_rule_version,
                "valid_until": valid_until,
                "input_versions": input_versions,
                "audit_reference": AuditReference(
                    audit_id=self._ids.new_id("audit"),
                    actor_id=owner_id,
                    recorded_at=now,
                ),
            }
        )
        return await self.create_draft(
            owner_id=owner_id,
            mode=mode,
            draft=draft,
            plan_reference=plan_reference,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            reference_price=reference_price,
        )

    @_transactional(commit=False)
    async def get_draft(self, *, owner_id: str, draft_id: str) -> StoredDraft:
        return await self._owned_draft(owner_id, draft_id)

    @_transactional(commit=False)
    async def get_order(self, *, owner_id: str, order_id: str) -> StoredOrder:
        return await self._owned_order(owner_id, order_id)

    @_transactional(commit=False)
    async def list_orders(self, *, owner_id: str) -> tuple[StoredOrder, ...]:
        orders = await self._repository.list_orders(owner_id)
        if any(order.owner_id != owner_id for order in orders):
            raise RuntimeError("repository returned an order owned by another user")
        return orders

    @_transactional(commit=False)
    async def list_fills(
        self,
        *,
        owner_id: str,
        order_id: str | None = None,
    ) -> tuple[SimulationFill, ...]:
        if order_id is not None:
            await self._owned_order(owner_id, order_id)
            return await self._repository.list_fills(order_id)
        owned_ids = {
            order.order_id for order in await self.list_orders(owner_id=owner_id)
        }
        fills = await self._repository.list_fills()
        return tuple(fill for fill in fills if fill.order_id in owned_ids)

    @_transactional(commit=False)
    async def list_order_views(
        self, *, owner_id: str
    ) -> tuple[StoredOrderView, ...]:
        orders = await self.list_orders(owner_id=owner_id)
        views = [await self._build_order_view(order) for order in orders]
        return tuple(views)

    @_transactional(commit=False)
    async def get_order_view(
        self, *, owner_id: str, order_id: str
    ) -> StoredOrderView:
        stored = await self._owned_order(owner_id, order_id)
        return await self._build_order_view(stored)

    async def _build_order_view(self, stored: StoredOrder) -> StoredOrderView:
        exchange = stored.exchange_order
        if exchange is None:
            raise ExecutionFailure(
                ExecutionFailureCode.PANDADATA_CAPABILITY_UNAVAILABLE,
                "fund order views are unavailable in simulation",
            )
        stored_draft = await self._repository.get_draft(
            stored.draft_reference.object_id
        )
        if stored_draft is None:
            raise ValueError("order draft not found for stored order")
        order_draft = stored_draft.draft
        fills = tuple(
            sorted(
                await self._repository.list_fills(exchange.order_id),
                key=lambda fill: fill.occurred_at,
            )
        )
        filled_quantity = sum((fill.quantity for fill in fills), Decimal("0"))
        filled_notional = sum(
            (fill.quantity * fill.price for fill in fills), Decimal("0")
        )
        total_fee = sum((fill.fee for fill in fills), Decimal("0"))
        average = (
            (filled_notional / filled_quantity).quantize(Decimal("0.00000001"))
            if filled_quantity > 0
            else None
        )
        return StoredOrderView(
            order_id=exchange.order_id,
            owner_id=stored.owner_id,
            order_kind="exchange",
            status=exchange.status.value,
            instrument_id=order_draft.instrument_id,
            side=order_draft.side.value,
            order_type=order_draft.order_type.value,
            time_in_force=(
                order_draft.time_in_force.value
                if order_draft.time_in_force is not None
                else None
            ),
            limit_price=order_draft.limit_price,
            quantity=exchange.quantity,
            cumulative_filled=exchange.cumulative_filled,
            remaining_quantity=exchange.quantity - exchange.cumulative_filled,
            average_fill_price=average,
            total_fee_rmb=total_fee,
            filled_notional_rmb=filled_notional.quantize(Decimal("0.01")),
            revision=exchange.revision,
            confirmed_at=stored_draft.confirmed_at,
            updated_at=exchange.audit_reference.recorded_at,
            draft_reference=stored.draft_reference,
            execution_error=stored.execution_error,
            fills=fills,
            timeline=self._build_timeline(exchange, stored_draft, fills),
        )

    @staticmethod
    def _build_timeline(
        exchange: ExchangeOrder,
        stored_draft: StoredDraft,
        fills: tuple[SimulationFill, ...],
    ) -> tuple[OrderTimelineEntry, ...]:
        entries: list[OrderTimelineEntry] = []
        if stored_draft.confirmed_at is not None:
            entries.append(
                OrderTimelineEntry(
                    status="confirmed",
                    occurred_at=stored_draft.confirmed_at,
                    actor_id=stored_draft.draft.audit_reference.actor_id,
                    detail="订单已确认",
                )
            )
        running = Decimal("0")
        for fill in fills:
            running += fill.quantity
            status = (
                ExchangeOrderStatus.FILLED.value
                if running >= exchange.quantity
                else ExchangeOrderStatus.PARTIALLY_FILLED.value
            )
            entries.append(
                OrderTimelineEntry(
                    status=status,
                    occurred_at=fill.occurred_at,
                    actor_id="simulation-execution-service",
                    detail=f"成交 {fill.quantity} @ {fill.price}",
                )
            )
        if exchange.status not in {
            ExchangeOrderStatus.PARTIALLY_FILLED,
            ExchangeOrderStatus.FILLED,
        }:
            entries.append(
                OrderTimelineEntry(
                    status=exchange.status.value,
                    occurred_at=exchange.audit_reference.recorded_at,
                    actor_id=exchange.audit_reference.actor_id,
                )
            )
        return tuple(sorted(entries, key=lambda entry: entry.occurred_at))

    @_transactional(commit=True)
    async def save_draft_revision(
        self,
        *,
        owner_id: str,
        updated: OrderDraft,
        expected_revision: int,
    ) -> StoredDraft:
        current = await self._owned_draft(owner_id, updated.draft_id)
        if current.draft.status is not OrderDraftStatus.DRAFT:
            raise ValueError("only draft status can be edited")
        if current.record_revision != expected_revision:
            raise ValueError("draft record revision changed")
        if updated.revision != current.draft.revision + 1:
            raise ValueError("draft edit must create exactly one domain revision")
        if updated.status is not OrderDraftStatus.DRAFT:
            raise ValueError("draft edit cannot change workflow status")
        replacement = current.model_copy(
            update={
                "draft": updated,
                "record_revision": current.record_revision + 1,
                "review": None,
                "risk_result": None,
                "cost_estimate": None,
                "immutable_summary_hash": None,
                "confirmed_at": None,
            }
        )
        await self._repository.save_draft(
            replacement,
            expected_revision=expected_revision,
        )
        return replacement

    @_transactional(commit=True)
    async def review(
        self,
        *,
        owner_id: str,
        draft_id: str,
        expected_revision: int,
    ) -> StoredDraft:
        current = await self._owned_draft(owner_id, draft_id)
        if current.record_revision != expected_revision:
            raise ValueError("draft record revision changed")
        if current.draft.status is not OrderDraftStatus.DRAFT:
            raise ValueError("draft is not editable")
        if current.mode is DraftMode.PLANNED:
            assert current.plan_reference is not None
            await self._plans.require_executable(current.plan_reference)
            review = None
        else:
            review = await self._manual_review.review(current)
        pending = current.draft.transition(
            OrderDraftStatus.PENDING_REVIEW,
            audit_reference=self._next_audit(
                current.draft.audit_reference,
                owner_id,
                "draft-review",
            ),
        )
        candidate = current.model_copy(
            update={
                "record_revision": current.record_revision + 1,
                "draft": pending,
                "review": review,
                "cost_estimate": self._project_cost(current),
            }
        )
        risk_result = await self._risk.evaluate(candidate)
        self._validate_risk_binding(pending, risk_result)
        summary_hash = _summary_hash(candidate, risk_result)
        reviewed = candidate.model_copy(
            update={
                "risk_result": risk_result,
                "immutable_summary_hash": summary_hash,
            }
        )
        await self._repository.save_draft(
            reviewed,
            expected_revision=expected_revision,
        )
        return reviewed

    @_transactional(commit=True)
    async def confirm_soft_risk(
        self,
        *,
        owner_id: str,
        draft_id: str,
        seen_reason_hash: str,
    ) -> StoredDraft:
        current = await self._owned_draft(owner_id, draft_id)
        if current.risk_result is None:
            raise ExecutionFailure(
                ExecutionFailureCode.RISK_CHECK_REQUIRED,
                "formal risk result is missing",
            )
        confirmed = await self._risk.confirm_soft(
            owner_id=owner_id,
            result=current.risk_result,
            seen_reason_hash=seen_reason_hash,
        )
        self._validate_risk_binding(current.draft, confirmed)
        candidate = current.model_copy(
            update={
                "record_revision": current.record_revision + 1,
                "risk_result": confirmed,
            }
        )
        updated = candidate.model_copy(
            update={"immutable_summary_hash": _summary_hash(candidate, confirmed)}
        )
        await self._repository.save_draft(
            updated,
            expected_revision=current.record_revision,
        )
        return updated

    @_transactional(commit=True)
    async def confirm(
        self,
        *,
        owner_id: str,
        draft_id: str,
        expected_revision: int,
        seen_summary_hash: str,
    ) -> StoredDraft:
        current = await self._owned_draft(owner_id, draft_id)
        if current.record_revision != expected_revision:
            raise ValueError("draft record revision changed")
        if current.immutable_summary_hash != seen_summary_hash:
            raise ValueError("immutable review summary changed")
        if current.risk_result is None:
            raise ExecutionFailure(
                ExecutionFailureCode.RISK_CHECK_REQUIRED,
                "formal risk result is missing",
            )
        now = self._clock.now()
        if not current.risk_result.can_submit_at(now):
            code = (
                ExecutionFailureCode.RISK_CHECK_EXPIRED
                if now >= current.risk_result.expires_at
                else ExecutionFailureCode.RISK_CHECK_REQUIRED
            )
            raise ExecutionFailure(code, "formal risk result does not permit submit")
        confirmed = current.draft.transition(
            OrderDraftStatus.CONFIRMED,
            audit_reference=self._next_audit(
                current.draft.audit_reference,
                owner_id,
                "draft-confirm",
            ),
        )
        updated = current.model_copy(
            update={
                "record_revision": current.record_revision + 1,
                "draft": confirmed,
                "confirmed_at": now,
            }
        )
        await self._repository.save_draft(
            updated,
            expected_revision=expected_revision,
        )
        return updated

    @_transactional(commit=True)
    async def submit(
        self,
        *,
        owner_id: str,
        draft_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> StoredOrder:
        draft = await self._owned_draft(owner_id, draft_id)
        if draft.draft.status is not OrderDraftStatus.CONFIRMED:
            raise ExecutionFailure(
                ExecutionFailureCode.USER_CONFIRMATION_REQUIRED,
                "draft must be confirmed before submission",
            )
        if draft.draft.order_type is OrderType.FUND:
            raise ExecutionFailure(
                ExecutionFailureCode.PANDADATA_CAPABILITY_UNAVAILABLE,
                "PandaData fund NAV/convert capability is unavailable",
            )
        existing = await self._repository.get_order_for_draft(draft_id)
        if existing is not None:
            return existing
        assert draft.draft.quantity is not None
        now = self._clock.now()
        exchange = ExchangeOrder(
            order_id=self._ids.new_id("order"),
            revision=1,
            status=ExchangeOrderStatus.SUBMITTING,
            idempotency_key=idempotency_key,
            draft_reference=_draft_reference(draft.draft),
            quantity=draft.draft.quantity,
            cumulative_filled=Decimal("0"),
            audit_reference=AuditReference(
                audit_id=self._ids.new_id("audit"),
                actor_id=owner_id,
                recorded_at=now,
            ),
        )
        submitting = StoredOrder(
            owner_id=owner_id,
            draft_reference=_draft_reference(draft.draft),
            exchange_order=exchange,
        )
        persisted = await self._repository.create_order(
            submitting,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        if persisted.exchange_order is None:
            return persisted
        if persisted.exchange_order.status is not ExchangeOrderStatus.SUBMITTING:
            return persisted
        outcome = await self._transport.submit(persisted)
        return await self._apply_submission_outcome(persisted, outcome)

    @_transactional(commit=True)
    async def reconcile(self, *, owner_id: str, order_id: str) -> StoredOrder:
        stored = await self._owned_order(owner_id, order_id)
        order = stored.exchange_order
        if order is None:
            raise ExecutionFailure(
                ExecutionFailureCode.PANDADATA_CAPABILITY_UNAVAILABLE,
                "fund NAV confirmation is unavailable",
            )
        if order.status is ExchangeOrderStatus.UNKNOWN:
            outcome = await self._transport.query(stored)
            stored = await self._apply_submission_outcome(stored, outcome)
            order = stored.exchange_order
            assert order is not None
        if order.status not in {
            ExchangeOrderStatus.ACCEPTED,
            ExchangeOrderStatus.PARTIALLY_FILLED,
        }:
            return stored
        draft = await self._repository.get_draft(order.draft_reference.object_id)
        if draft is None:
            raise ValueError("order draft not found")
        bar = await self._bars.next_bar(draft.draft)
        if bar is None:
            raise ExecutionFailure(
                ExecutionFailureCode.MARKET_DATA_MISSING,
                "next available PandaData daily bar is unavailable",
            )
        result = self._matcher.match(
            draft.draft,
            bar,
            remaining_quantity=order.quantity - order.cumulative_filled,
        )
        if result.fill_quantity == 0 or result.fill_price is None:
            return stored
        ledger_fill_id = await self._ledger.record_exchange_fill(
            owner_id=owner_id,
            draft=draft.draft,
            order=order,
            quantity=result.fill_quantity,
            price=result.fill_price,
            fee=result.fee,
            slippage_bps=result.slippage_bps,
            market_evidence=result.market_evidence,
            model_version=result.model_version,
            rule_version=result.rule_version,
            idempotency_key=f"fill:{order.order_id}:{order.revision + 1}",
        )
        updated_order = order.record_fill(
            result.fill_quantity,
            audit_reference=self._next_audit(
                order.audit_reference,
                "simulation-execution-service",
                "fill",
            ),
        )
        updated = stored.model_copy(update={"exchange_order": updated_order})
        await self._repository.save_order(updated, expected_revision=order.revision)
        fill = SimulationFill(
            fill_id=self._ids.new_id("fill"),
            order_id=order.order_id,
            account_id=draft.draft.account_id,
            instrument_id=draft.draft.instrument_id,
            side=draft.draft.side,
            quantity=result.fill_quantity,
            price=result.fill_price,
            fee=result.fee,
            slippage_bps=result.slippage_bps,
            market_evidence=result.market_evidence,
            model_version=result.model_version,
            rule_version=result.rule_version,
            occurred_at=self._clock.now(),
            ledger_fill_id=ledger_fill_id,
        )
        await self._repository.append_fill(fill)
        return updated

    @_transactional(commit=True)
    async def cancel(self, *, owner_id: str, order_id: str) -> StoredOrder:
        stored = await self._owned_order(owner_id, order_id)
        order = stored.exchange_order
        if order is None or order.status not in {
            ExchangeOrderStatus.ACCEPTED,
            ExchangeOrderStatus.PARTIALLY_FILLED,
        }:
            raise ValueError("order cannot be cancelled")
        cancelling = order.transition(
            ExchangeOrderStatus.CANCELLING,
            audit_reference=self._next_audit(
                order.audit_reference,
                owner_id,
                "cancel-request",
            ),
        )
        pending = stored.model_copy(update={"exchange_order": cancelling})
        await self._repository.save_order(pending, expected_revision=order.revision)
        outcome = await self._transport.cancel(pending)
        target = {
            SubmissionStatus.ACCEPTED: ExchangeOrderStatus.CANCELLED,
            SubmissionStatus.UNKNOWN: ExchangeOrderStatus.UNKNOWN,
            SubmissionStatus.REJECTED: ExchangeOrderStatus.UNKNOWN,
        }[outcome.status]
        final = cancelling.transition(
            target,
            audit_reference=self._next_audit(
                cancelling.audit_reference,
                "simulation-execution-service",
                "cancel-result",
            ),
        )
        result = pending.model_copy(
            update={
                "exchange_order": final,
                "execution_error": outcome.reason,
            }
        )
        await self._repository.save_order(result, expected_revision=cancelling.revision)
        return result

    async def _apply_submission_outcome(
        self,
        stored: StoredOrder,
        outcome: SubmissionOutcome,
    ) -> StoredOrder:
        order = stored.exchange_order
        if order is None:
            return stored
        target = {
            SubmissionStatus.ACCEPTED: ExchangeOrderStatus.ACCEPTED,
            SubmissionStatus.REJECTED: ExchangeOrderStatus.REJECTED,
            SubmissionStatus.UNKNOWN: ExchangeOrderStatus.UNKNOWN,
        }[outcome.status]
        transitioned = order.transition(
            target,
            audit_reference=self._next_audit(
                order.audit_reference,
                "simulation-execution-service",
                "submission-result",
            ),
        )
        updated = stored.model_copy(
            update={
                "exchange_order": transitioned,
                "execution_error": outcome.reason,
            }
        )
        await self._repository.save_order(updated, expected_revision=order.revision)
        return updated

    async def _owned_draft(self, owner_id: str, draft_id: str) -> StoredDraft:
        draft = await self._repository.get_draft(draft_id)
        if draft is None or draft.owner_id != owner_id:
            raise PermissionError("order draft not found")
        return draft

    def _project_cost(self, stored: StoredDraft) -> CostEstimate | None:
        """Project notional/fee/total using the authoritative rule set.

        Returns ``None`` when a reference price is unavailable (e.g. a market
        order without an observed quote), so the UI can show that the estimate
        is unavailable rather than fabricate figures.
        """
        draft = stored.draft
        quantity = draft.quantity
        if quantity is None or quantity <= 0:
            return None
        rules = self._matcher.rules
        if draft.order_type is OrderType.LIMIT and draft.limit_price is not None:
            price = draft.limit_price
            price_source = "limit_price"
        elif draft.order_type is OrderType.MARKET and stored.reference_price is not None:
            direction = (
                Decimal("1")
                if draft.side in {OrderSide.BUY, OrderSide.COVER}
                else Decimal("-1")
            )
            price = (
                stored.reference_price
                * (Decimal("1") + direction * rules.slippage_bps / Decimal("10000"))
            ).quantize(Decimal("0.00000001"))
            price_source = "market_reference"
        else:
            return None
        cents = Decimal("0.01")
        notional = (price * quantity).quantize(cents)
        fee = (price * quantity * rules.fee_bps / Decimal("10000")).quantize(cents)
        is_outflow = draft.side in {OrderSide.BUY, OrderSide.COVER}
        total = notional + fee if is_outflow else notional - fee
        return CostEstimate(
            reference_price=price,
            price_source=price_source,
            quantity=quantity,
            notional=notional,
            fee=fee,
            total=total,
            cash_flow="outflow" if is_outflow else "inflow",
            fee_bps=rules.fee_bps,
            slippage_bps=rules.slippage_bps,
            rule_version=rules.version,
        )

    async def _owned_order(self, owner_id: str, order_id: str) -> StoredOrder:
        order = await self._repository.get_order(order_id)
        if order is None or order.owner_id != owner_id:
            raise PermissionError("order not found")
        return order

    @staticmethod
    def _validate_risk_binding(
        draft: OrderDraft,
        result: RiskCheckResult,
    ) -> None:
        if result.order_version != _draft_reference(draft):
            raise ValueError("formal risk result is bound to another draft revision")
        if result.status is RiskCheckStatus.CHECKING:
            raise ValueError("formal risk result is incomplete")

    def _next_audit(
        self,
        previous: AuditReference,
        actor_id: str,
        prefix: str,
    ) -> AuditReference:
        now = self._clock.now()
        if now <= previous.recorded_at:
            now = previous.recorded_at + timedelta(microseconds=1)
        return AuditReference(
            audit_id=self._ids.new_id(prefix),
            actor_id=actor_id,
            recorded_at=now,
        )


def _draft_reference(draft: OrderDraft) -> VersionReference:
    return VersionReference(
        object_type="order_draft",
        object_id=draft.draft_id,
        version=str(draft.revision),
    )


def _summary_hash(draft: StoredDraft, risk: RiskCheckResult) -> str:
    payload = {
        "draft": draft.draft.model_dump(mode="json"),
        "review": (
            draft.review.model_dump(mode="json") if draft.review is not None else None
        ),
        "cost_estimate": (
            draft.cost_estimate.model_dump(mode="json")
            if draft.cost_estimate is not None
            else None
        ),
        "risk": risk.model_dump(mode="json"),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
