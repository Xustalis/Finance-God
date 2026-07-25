"""Simulation service wiring — port adapters and factory for server.py.

Provides lightweight adapter implementations for the 9 Protocol ports required
by ``SimulationExecutionService``, plus the ``SimulationAccountApplication``
Protocol used by the simulation REST routes.  These adapters target the
*simulation* use-case only; they are **not** production broker or risk
implementations.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from finance_god.api.simulation import (
    SimulationAccountCreate,
    SimulationAccountReset,
    SimulationAccountView,
    SimulationPositionView,
)
from finance_god.application.ledger_service import (
    CreateAccountCommand,
    FreezeCashCommand,
    RecordBuyFillCommand,
    RecordSellFillCommand,
    ResetAccountCommand,
    SimulationLedgerService,
)
from finance_god.application.ports import UnitOfWorkFactory
from finance_god.application.simulation_clock import SimulationClockService
from finance_god.domain import (
    AccountStatus,
    AuditReference,
    ExchangeOrder,
    Money,
    OrderDraft,
    OrderSide,
    ReservationKind,
    RiskCheckResult,
    RiskCheckStatus,
    RiskReason,
    RiskSeverity,
    VersionReference,
)
from finance_god.execution import (
    DeterministicMatcher,
    ManualReviewResult,
    SimulationExecutionService,
    StoredDraft,
    StoredOrder,
    SubmissionOutcome,
    SubmissionStatus,
)
from finance_god.execution.contracts import (
    SimulationBar,
)
from finance_god.infrastructure.mandate_provider import (
    PersistentAuthorizationProvider,
)
from finance_god.infrastructure.persistence.simulation_uow import (
    SimulationUnitOfWork,
)
from finance_god.infrastructure.trade_plan_port import PersistentTradePlanPort
from finance_god.market_data import MarketBar, MarketDataService
from finance_god.trading.mandate import (
    InvestmentMandate,
    evaluate_order_authorization,
    order_notional,
)

ZERO = Decimal("0")
CNY = "CNY"


# ---------------------------------------------------------------------------
# Simple utility ports
# ---------------------------------------------------------------------------


class SystemClock:
    """Wall-clock backed by ``datetime.now(UTC)``."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class UuidIdGenerator:
    """Generate prefixed hex IDs via ``uuid4``."""

    def new_id(self, prefix: str) -> str:
        return f"{prefix}-{uuid4().hex[:16]}"


# ---------------------------------------------------------------------------
# Domain ports
# ---------------------------------------------------------------------------


class LedgerAccountOwnership:
    """Verify account ownership via the ledger UnitOfWork."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def require_current_account(
        self, owner_id: str, account_id: str
    ) -> None:
        async with self._uow_factory() as uow:
            account = await uow.accounts.get(account_id)
            if (
                account is None
                or account.owner_user_id != owner_id
                or account.status is not AccountStatus.ACTIVE
                or not account.current
            ):
                raise PermissionError(
                    f"active simulation account {account_id} not found for owner"
                )


class AutoPassManualReview:
    """Simulation-only: automatically pass manual review for non-planned drafts."""

    async def review(self, draft: StoredDraft) -> ManualReviewResult:
        return ManualReviewResult(
            succeeded=True,
            summary="simulation auto-pass: no manual review required",
        )


class SimulationRiskAdapter:
    """Risk evaluation enforcing the owner's persisted investment mandate.

    When an authorization provider is wired, the draft's owner mandate is loaded
    and checked deterministically (status / side / order type / market / single
    order amount); any hard denial yields a BLOCKED result so submission is
    stopped at the risk step.  Without a provider (unit tests that only exercise
    ``confirm_soft``) evaluation stays PASSED.
    """

    def __init__(
        self,
        clock: SystemClock,
        ids: UuidIdGenerator,
        authorization: PersistentAuthorizationProvider | None = None,
    ) -> None:
        self._clock = clock
        self._ids = ids
        self._authorization = authorization

    async def evaluate(self, draft: StoredDraft) -> RiskCheckResult:
        mandate = (
            await self._authorization.ensure_current(draft.owner_id)
            if self._authorization is not None
            else None
        )
        now = self._clock.now()
        order_version = VersionReference(
            object_type="order_draft",
            object_id=draft.draft.draft_id,
            version=str(draft.draft.revision),
        )
        reasons = self._authorization_reasons(draft, mandate, now)
        status = RiskCheckStatus.BLOCKED if reasons else RiskCheckStatus.PASSED
        return RiskCheckResult.model_validate(
            {
                "risk_check_id": self._ids.new_id("risk"),
                "revision": 1,
                "status": status,
                "order_version": order_version,
                "rule_version": VersionReference(
                    object_type="risk_rules",
                    object_id="simulation-risk-v1",
                    version="1",
                ),
                "reasons": reasons,
                "checked_at": now,
                "expires_at": now + timedelta(minutes=30),
                "input_versions": (order_version,),
                "audit_reference": {
                    "audit_id": self._ids.new_id("audit"),
                    "actor_id": "simulation-risk-adapter",
                    "recorded_at": now,
                },
            }
        )

    @staticmethod
    def _authorization_reasons(
        draft: StoredDraft,
        mandate: InvestmentMandate | None,
        now: datetime,
    ) -> tuple[RiskReason, ...]:
        if mandate is None:
            return ()
        order = draft.draft
        notional = order_notional(
            order_type=order.order_type.value,
            quantity=order.quantity,
            amount=order.amount,
            limit_price=order.limit_price,
            reference_price=draft.reference_price,
        )
        denials = evaluate_order_authorization(
            mandate,
            now=now,
            side=order.side.value,
            order_type=order.order_type.value,
            instrument_id=order.instrument_id,
            notional=notional,
        )
        return tuple(
            RiskReason(
                code=denial.code,
                severity=RiskSeverity.HARD,
                message=denial.message,
            )
            for denial in denials
        )

    async def confirm_soft(
        self,
        *,
        owner_id: str,
        result: RiskCheckResult,
        seen_reason_hash: str,
    ) -> RiskCheckResult:
        if seen_reason_hash != result.reason_hash:
            raise ValueError("risk reason summary changed")
        now = self._clock.now()
        return result.confirm_soft_risk(
            AuditReference(
                audit_id=self._ids.new_id("audit"),
                actor_id=owner_id,
                recorded_at=now,
            )
        )


class SimulationSubmissionTransport:
    """Pure simulation transport — always accepts submissions."""

    async def submit(self, order: StoredOrder) -> SubmissionOutcome:
        return SubmissionOutcome(status=SubmissionStatus.ACCEPTED)

    async def query(self, order: StoredOrder) -> SubmissionOutcome:
        return SubmissionOutcome(status=SubmissionStatus.ACCEPTED)

    async def cancel(self, order: StoredOrder) -> SubmissionOutcome:
        return SubmissionOutcome(status=SubmissionStatus.ACCEPTED)


class MarketDataBarProvider:
    """Adapt normalized PandaData bars into deterministic simulation bars."""

    def __init__(
        self,
        market_data: MarketDataService,
        simulation_clock: SimulationClockService,
    ) -> None:
        self._market_data = market_data
        self._simulation_clock = simulation_clock

    async def next_bar(
        self,
        draft: OrderDraft,
        *,
        submitted_at: datetime,
    ) -> SimulationBar | None:
        current = await self._simulation_clock.get_for_account(draft.account_id)
        trading_date = submitted_at.astimezone(
            ZoneInfo("Asia/Shanghai")
        ).strftime("%Y%m%d")
        result = await asyncio.to_thread(
            self._market_data.read_historical_minute_bars,
            draft.instrument_id,
            trading_date=trading_date,
            limit=500,
        )
        candidates: list[tuple[datetime, MarketBar]] = []
        for bar in result.bars:
            observed_at = datetime.fromisoformat(bar.provider_time)
            if observed_at.tzinfo is None:
                continue
            if submitted_at < observed_at <= current.current_time:
                candidates.append((observed_at, bar))
        if not candidates:
            return None
        observed_at, selected = min(candidates, key=lambda item: item[0])
        return SimulationBar(
            instrument_id=draft.instrument_id,
            market="CN",
            trading_day=observed_at.date().isoformat(),
            open=selected.open,
            high=selected.high,
            low=selected.low,
            close=selected.close,
            volume=selected.volume,
            upstream_timestamp=observed_at,
            ingested_at=datetime.now(UTC),
            frequency=result.frequency,
            evidence=VersionReference(
                object_type="simulation_historical_bar",
                object_id=draft.instrument_id,
                version=f"{selected.provider_time}:clock:{current.revision}",
            ),
            stale=selected.freshness in {
                "stale",
                "error",
                "unavailable",
                "missing",
            },
            conflict=False,
        )


class LedgerFillAdapter:
    """Record exchange fills into the simulation ledger.

    Bridges ``LedgerExecutionPort`` to ``SimulationLedgerService``.
    """

    def __init__(
        self,
        ledger: SimulationLedgerService,
        clock: SystemClock,
        ids: UuidIdGenerator,
    ) -> None:
        self._ledger = ledger
        self._clock = clock
        self._ids = ids

    async def record_exchange_fill(
        self,
        *,
        owner_id: str,
        draft: OrderDraft,
        order: ExchangeOrder,
        quantity: Decimal,
        price: Decimal,
        fee: Decimal,
        slippage_bps: Decimal,
        market_evidence: VersionReference,
        model_version: str,
        rule_version: str,
        idempotency_key: str,
    ) -> str:
        source = VersionReference(
            object_type="exchange_order",
            object_id=order.order_id,
            version=str(order.revision),
        )
        base = {
            "owner_user_id": owner_id,
            "idempotency_key": idempotency_key,
            "correlation_id": self._ids.new_id("corr"),
            "causation_id": self._ids.new_id("caus"),
            "source": source,
            "account_id": draft.account_id,
            "order_id": order.order_id,
            "instrument_id": draft.instrument_id,
            "quantity": quantity,
            "price": price,
            "fee": fee,
            "currency": CNY,
            "slippage_bps": slippage_bps,
            "market_evidence": market_evidence,
            "model_version": model_version,
        }
        if draft.side is OrderSide.BUY:
            reservation_id = await self._ledger.freeze_cash(
                FreezeCashCommand(
                    owner_user_id=owner_id,
                    idempotency_key=f"{idempotency_key}:reserve",
                    correlation_id=self._ids.new_id("corr"),
                    causation_id=self._ids.new_id("caus"),
                    source=source,
                    account_id=draft.account_id,
                    order_id=order.order_id,
                    instrument_id=draft.instrument_id,
                    amount=Money(
                        currency=CNY,
                        amount=price * quantity + fee,
                    ),
                    reservation_kind=ReservationKind.CASH_BUY,
                )
            )
            command = RecordBuyFillCommand(
                **base,
                reservation_id=reservation_id,
            )
            return await self._ledger.record_buy_fill(command)
        command = RecordSellFillCommand(**base)
        return await self._ledger.record_sell_fill(command)


# ---------------------------------------------------------------------------
# SimulationAccountApplication implementation
# ---------------------------------------------------------------------------


class SimulationAccountApplicationImpl:
    """Bridge between the simulation REST API and the ledger service."""

    def __init__(
        self,
        ledger: SimulationLedgerService,
        uow_factory: UnitOfWorkFactory,
        clock: SystemClock,
        ids: UuidIdGenerator,
        simulation_clock: SimulationClockService,
    ) -> None:
        self._ledger = ledger
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids
        self._simulation_clock = simulation_clock

    async def create(
        self,
        *,
        owner_id: str,
        request: SimulationAccountCreate,
        idempotency_key: str,
        request_hash: str,
    ) -> SimulationAccountView:
        source = VersionReference(
            object_type="api",
            object_id="simulation-account-create",
            version="1",
        )
        command = CreateAccountCommand(
            owner_user_id=owner_id,
            idempotency_key=idempotency_key,
            correlation_id=self._ids.new_id("corr"),
            causation_id=self._ids.new_id("caus"),
            source=source,
            initial_cash_rmb=request.initial_cash_rmb,
            business_time=request.simulation_start_at,
        )
        account_id = await self._ledger.create_account(command)
        await self._simulation_clock.create(account_id, request.simulation_start_at)
        return await self._view(owner_id, account_id)

    async def reset(
        self,
        *,
        owner_id: str,
        account_id: str,
        request: SimulationAccountReset,
        idempotency_key: str,
        request_hash: str,
    ) -> SimulationAccountView:
        source = VersionReference(
            object_type="api",
            object_id="simulation-account-reset",
            version="1",
        )
        command = ResetAccountCommand(
            owner_user_id=owner_id,
            idempotency_key=idempotency_key,
            correlation_id=self._ids.new_id("corr"),
            causation_id=self._ids.new_id("caus"),
            source=source,
            account_id=account_id,
            initial_cash_rmb=request.initial_cash_rmb,
            business_time=request.simulation_start_at,
        )
        new_id = await self._ledger.reset_account(command)
        await self._simulation_clock.create(new_id, request.simulation_start_at)
        return await self._view(owner_id, new_id)

    async def current(self, *, owner_id: str) -> SimulationAccountView | None:
        async with self._uow_factory() as uow:
            account = await uow.accounts.get_current(owner_id)
            if account is None:
                return None
            cash_list = await uow.account_projections.list(account.account_id)
            cny = next(
                (c for c in cash_list if c.currency == CNY), None
            )
            simulation_clock = await self._simulation_clock.find_for_account(
                account.account_id
            )
            return SimulationAccountView(
                account_id=account.account_id,
                owner_id=account.owner_user_id,
                status=account.status.value,
                cash_total_rmb=cny.total if cny else account.initial_cash_rmb,
                cash_available_rmb=cny.rmb_available if cny else account.initial_cash_rmb,
                cash_frozen_rmb=cny.frozen if cny else ZERO,
                margin_rmb=cny.margin if cny else ZERO,
                revision=account.revision,
                simulation_time=(
                    simulation_clock.current_time if simulation_clock else None
                ),
            )

    async def positions(
        self, *, owner_id: str
    ) -> tuple[SimulationPositionView, ...]:
        async with self._uow_factory() as uow:
            account = await uow.accounts.get_current(owner_id)
            if account is None:
                return ()
            projections = await uow.position_projections.list(account.account_id)
            return tuple(
                SimulationPositionView(
                    account_id=projection.account_id,
                    instrument_id=projection.instrument_id,
                    currency=projection.currency,
                    long_quantity=projection.long_quantity,
                    settled_quantity=projection.settled_quantity,
                    frozen_quantity=projection.frozen_quantity,
                    cost_rmb=projection.long_cost_rmb,
                    revision=projection.revision,
                )
                for projection in projections
                if projection.long_quantity > ZERO
                or projection.short_quantity > ZERO
            )

    async def _view(
        self, owner_id: str, account_id: str
    ) -> SimulationAccountView:
        async with self._uow_factory() as uow:
            account = await uow.accounts.get(account_id)
            if account is None:
                raise LookupError("simulation account not found")
            cash_list = await uow.account_projections.list(account_id)
            cny = next(
                (c for c in cash_list if c.currency == CNY), None
            )
            simulation_clock = await self._simulation_clock.find_for_account(
                account.account_id
            )
            return SimulationAccountView(
                account_id=account.account_id,
                owner_id=account.owner_user_id,
                status=account.status.value,
                cash_total_rmb=cny.total if cny else account.initial_cash_rmb,
                cash_available_rmb=cny.rmb_available if cny else account.initial_cash_rmb,
                cash_frozen_rmb=cny.frozen if cny else ZERO,
                margin_rmb=cny.margin if cny else ZERO,
                revision=account.revision,
                simulation_time=(
                    simulation_clock.current_time if simulation_clock else None
                ),
            )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_simulation_services(
    *,
    uow_factory: UnitOfWorkFactory,
    simulation_session_factory: Callable[[], AsyncSession],
    ledger: SimulationLedgerService,
    market_data: MarketDataService,
    authorization: PersistentAuthorizationProvider | None = None,
    simulation_clock: SimulationClockService | None = None,
) -> tuple[SimulationExecutionService, SimulationAccountApplicationImpl]:
    """Wire all port adapters and return (execution, accounts) pair."""
    clock = SystemClock()
    ids = UuidIdGenerator()
    account_clock = simulation_clock or SimulationClockService(simulation_session_factory)

    execution = SimulationExecutionService(
        uow_factory=lambda: SimulationUnitOfWork(
            simulation_session_factory
        ),
        accounts=LedgerAccountOwnership(uow_factory),
        plans=PersistentTradePlanPort(simulation_session_factory, clock),
        manual_review=AutoPassManualReview(),
        risk=SimulationRiskAdapter(clock, ids, authorization),
        transport=SimulationSubmissionTransport(),
        bars=MarketDataBarProvider(market_data, account_clock),
        ledger=LedgerFillAdapter(ledger, clock, ids),
        matcher=DeterministicMatcher(),
        clock=clock,
        ids=ids,
    )
    accounts = SimulationAccountApplicationImpl(
        ledger, uow_factory, clock, ids, account_clock
    )
    return execution, accounts
