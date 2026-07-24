"""Simulation service wiring — port adapters and factory for server.py.

Provides lightweight adapter implementations for the 9 Protocol ports required
by ``SimulationExecutionService``, plus the ``SimulationAccountApplication``
Protocol used by the simulation REST routes.  These adapters target the
*simulation* use-case only; they are **not** production broker or risk
implementations.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from finance_god.application.ledger_service import (
    CreateAccountCommand,
    RecordBuyFillCommand,
    RecordSellFillCommand,
    ResetAccountCommand,
    SimulationLedgerService,
)
from finance_god.application.ports import UnitOfWorkFactory
from finance_god.domain import (
    AccountStatus,
    ExchangeOrder,
    OrderDraft,
    OrderSide,
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
    SimulationFill,
    StoredDraft,
    StoredOrder,
    SubmissionOutcome,
    SubmissionStatus,
)
from finance_god.execution.contracts import (
    AccountOwnershipPort,
    BarProvider,
    ExecutionRepositoryPort,
    LedgerExecutionPort,
    SimulationBar,
    SubmissionTransport,
    TradePlanPort,
    TrustedRiskPort,
)
from finance_god.execution.contracts import Clock as ExecutionClock
from finance_god.execution.contracts import IdGenerator as ExecutionIdGenerator
from finance_god.infrastructure.persistence.simulation_repository import (
    SimulationRepository,
)

from finance_god.api.simulation import (
    SimulationAccountApplication,
    SimulationAccountCreate,
    SimulationAccountReset,
    SimulationAccountView,
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


class PermissiveTradePlanPort:
    """MANUAL drafts never call this; PLANNED drafts are not yet supported."""

    async def require_executable(self, reference: VersionReference) -> None:
        raise ValueError(
            "trade plan service is not yet available; use MANUAL draft mode"
        )


class AutoPassManualReview:
    """Simulation-only: automatically pass manual review for non-planned drafts."""

    async def review(self, draft: StoredDraft) -> ManualReviewResult:
        return ManualReviewResult(
            succeeded=True,
            summary="simulation auto-pass: no manual review required",
        )


class SimulationRiskAdapter:
    """Simplified risk evaluation that always passes for simulation.

    Generates a valid ``RiskCheckResult`` with PASSED status and no reasons,
    allowing the draft lifecycle to proceed through review → confirm → submit.
    """

    def __init__(self, clock: SystemClock, ids: UuidIdGenerator) -> None:
        self._clock = clock
        self._ids = ids

    async def evaluate(self, draft: StoredDraft) -> RiskCheckResult:
        now = self._clock.now()
        order_version = VersionReference(
            object_type="order_draft",
            object_id=draft.draft.draft_id,
            version=str(draft.draft.revision),
        )
        return RiskCheckResult.model_validate(
            {
                "risk_check_id": self._ids.new_id("risk"),
                "revision": 1,
                "status": RiskCheckStatus.PASSED,
                "order_version": order_version,
                "rule_version": VersionReference(
                    object_type="risk_rules",
                    object_id="simulation-risk-v1",
                    version="1",
                ),
                "reasons": (),
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

    async def confirm_soft(
        self,
        *,
        owner_id: str,
        result: RiskCheckResult,
        seen_reason_hash: str,
    ) -> RiskCheckResult:
        now = self._clock.now()
        return result.model_copy(
            update={
                "soft_confirmation": {
                    "audit_id": self._ids.new_id("audit"),
                    "actor_id": owner_id,
                    "recorded_at": now,
                },
            }
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
    """Return None — reconcile requires real PandaData bars which may be
    unavailable.  The execution service will raise MARKET_DATA_MISSING,
    which is the correct safe behaviour."""

    async def next_bar(self, draft: OrderDraft) -> SimulationBar | None:
        return None


class PerRequestSimulationRepository:
    """Wrap SimulationRepository to create a fresh session per operation.

    ``SimulationRepository`` holds an ``AsyncSession`` reference.  In an HTTP
    server each request should use its own session.  This wrapper delegates
    every ``ExecutionRepositoryPort`` call to a freshly-created repository.
    """

    def __init__(
        self, session_factory: Callable[[], AsyncSession]
    ) -> None:
        self._session_factory = session_factory

    def _repo(self) -> SimulationRepository:
        return SimulationRepository(self._session_factory())

    async def create_draft(self, draft: StoredDraft, *, idempotency_key: str, request_hash: str) -> StoredDraft:
        return await self._repo().create_draft(draft, idempotency_key=idempotency_key, request_hash=request_hash)

    async def get_draft(self, draft_id: str) -> StoredDraft | None:
        return await self._repo().get_draft(draft_id)

    async def save_draft(self, draft: StoredDraft, *, expected_revision: int) -> None:
        await self._repo().save_draft(draft, expected_revision=expected_revision)

    async def create_order(self, order: StoredOrder, *, idempotency_key: str, request_hash: str) -> StoredOrder:
        return await self._repo().create_order(order, idempotency_key=idempotency_key, request_hash=request_hash)

    async def get_order(self, order_id: str) -> StoredOrder | None:
        return await self._repo().get_order(order_id)

    async def get_order_for_draft(self, draft_id: str) -> StoredOrder | None:
        return await self._repo().get_order_for_draft(draft_id)

    async def save_order(self, order: StoredOrder, *, expected_revision: int) -> None:
        await self._repo().save_order(order, expected_revision=expected_revision)

    async def append_fill(self, fill: SimulationFill) -> None:
        await self._repo().append_fill(fill)

    async def list_fills(self, order_id: str | None = None) -> tuple[SimulationFill, ...]:
        return await self._repo().list_fills(order_id)

    async def list_orders(self, owner_id: str) -> tuple[StoredOrder, ...]:
        return await self._repo().list_orders(owner_id)


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
        now = self._clock.now()
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
            command = RecordBuyFillCommand(
                **base,
                reservation_id=self._ids.new_id("reservation"),
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
    ) -> None:
        self._ledger = ledger
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids

    async def create(
        self,
        *,
        owner_id: str,
        request: SimulationAccountCreate,
        idempotency_key: str,
        request_hash: str,
    ) -> SimulationAccountView:
        now = self._clock.now()
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
        )
        account_id = await self._ledger.create_account(command)
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
        )
        new_id = await self._ledger.reset_account(command)
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
            return SimulationAccountView(
                account_id=account.account_id,
                owner_id=account.owner_user_id,
                status=account.status.value,
                cash_total_rmb=cny.total if cny else account.initial_cash_rmb,
                cash_available_rmb=cny.rmb_available if cny else account.initial_cash_rmb,
                cash_frozen_rmb=cny.frozen if cny else ZERO,
                margin_rmb=cny.margin if cny else ZERO,
                revision=account.revision,
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
            return SimulationAccountView(
                account_id=account.account_id,
                owner_id=account.owner_user_id,
                status=account.status.value,
                cash_total_rmb=cny.total if cny else account.initial_cash_rmb,
                cash_available_rmb=cny.rmb_available if cny else account.initial_cash_rmb,
                cash_frozen_rmb=cny.frozen if cny else ZERO,
                margin_rmb=cny.margin if cny else ZERO,
                revision=account.revision,
            )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_simulation_services(
    *,
    uow_factory: UnitOfWorkFactory,
    simulation_session_factory: Callable[[], AsyncSession],
    ledger: SimulationLedgerService,
) -> tuple[SimulationExecutionService, SimulationAccountApplicationImpl]:
    """Wire all port adapters and return (execution, accounts) pair."""
    clock = SystemClock()
    ids = UuidIdGenerator()
    repository = PerRequestSimulationRepository(simulation_session_factory)

    execution = SimulationExecutionService(
        repository=repository,
        accounts=LedgerAccountOwnership(uow_factory),
        plans=PermissiveTradePlanPort(),
        manual_review=AutoPassManualReview(),
        risk=SimulationRiskAdapter(clock, ids),
        transport=SimulationSubmissionTransport(),
        bars=MarketDataBarProvider(),
        ledger=LedgerFillAdapter(ledger, clock, ids),
        matcher=DeterministicMatcher(),
        clock=clock,
        ids=ids,
    )
    accounts = SimulationAccountApplicationImpl(ledger, uow_factory, clock, ids)
    return execution, accounts
