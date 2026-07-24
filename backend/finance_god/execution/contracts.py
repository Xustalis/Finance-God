from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from finance_god.domain import (
    ExchangeOrder,
    FundOrder,
    OrderDraft,
    OrderSide,
    RiskCheckResult,
    VersionReference,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DraftMode(str, Enum):
    PLANNED = "planned"
    MANUAL = "manual"


class ExecutionFailureCode(str, Enum):
    PANDADATA_CAPABILITY_UNAVAILABLE = "PANDADATA_CAPABILITY_UNAVAILABLE"
    MARKET_DATA_MISSING = "MARKET_DATA_MISSING"
    MARKET_DATA_STALE = "MARKET_DATA_STALE"
    MARKET_DATA_CONFLICT = "MARKET_DATA_CONFLICT"
    RISK_CHECK_REQUIRED = "RISK_CHECK_REQUIRED"
    RISK_CHECK_EXPIRED = "RISK_CHECK_EXPIRED"
    USER_CONFIRMATION_REQUIRED = "USER_CONFIRMATION_REQUIRED"
    SUBMISSION_UNKNOWN = "SUBMISSION_UNKNOWN"
    UNSUPPORTED_OPERATION = "UNSUPPORTED_OPERATION"
    REVISION_CONFLICT = "REVISION_CONFLICT"


class ExecutionFailure(RuntimeError):
    def __init__(self, code: ExecutionFailureCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class ManualReviewResult(StrictModel):
    succeeded: bool
    summary: str | None = Field(default=None, max_length=4_000)
    error: str | None = Field(default=None, max_length=1_000)

    @model_validator(mode="after")
    def validate_result(self) -> ManualReviewResult:
        if self.succeeded == (self.error is not None):
            raise ValueError("successful review requires no error; failure requires error")
        return self


class CostEstimate(StrictModel):
    """Backend-computed pre-submission cost projection for a draft.

    All monetary values follow the authoritative ``SimulationRuleSet``; the
    frontend must display these figures rather than compute its own.  This is an
    *estimate* — the executed fill uses the next real PandaData bar at reconcile.
    """

    reference_price: Decimal = Field(gt=0)
    price_source: str = Field(pattern=r"^(limit_price|market_reference)$")
    quantity: Decimal = Field(gt=0)
    notional: Decimal = Field(ge=0)
    fee: Decimal = Field(ge=0)
    total: Decimal
    cash_flow: str = Field(pattern=r"^(outflow|inflow)$")
    fee_bps: Decimal = Field(ge=0)
    slippage_bps: Decimal = Field(ge=0)
    currency: str = Field(default="CNY", min_length=3, max_length=3)
    rule_version: str = Field(min_length=1, max_length=80)


class StoredDraft(StrictModel):
    record_revision: int = Field(default=1, ge=1)
    owner_id: str = Field(min_length=1, max_length=160)
    mode: DraftMode
    draft: OrderDraft
    plan_reference: VersionReference | None = None
    reference_price: Decimal | None = Field(default=None, gt=0)
    review: ManualReviewResult | None = None
    risk_result: RiskCheckResult | None = None
    cost_estimate: CostEstimate | None = None
    immutable_summary_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    confirmed_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_mode(self) -> StoredDraft:
        if self.mode is DraftMode.PLANNED and self.plan_reference is None:
            raise ValueError("planned draft requires TradePlan reference")
        if self.mode is DraftMode.MANUAL and self.plan_reference is not None:
            raise ValueError("manual draft cannot carry TradePlan reference")
        return self


class StoredOrder(StrictModel):
    owner_id: str = Field(min_length=1, max_length=160)
    draft_reference: VersionReference
    exchange_order: ExchangeOrder | None = None
    fund_order: FundOrder | None = None
    execution_error: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def validate_order(self) -> StoredOrder:
        if (self.exchange_order is None) == (self.fund_order is None):
            raise ValueError("stored order requires exactly one order type")
        return self

    @property
    def order_id(self) -> str:
        order = self.exchange_order or self.fund_order
        assert order is not None
        return order.order_id


class SimulationBar(StrictModel):
    instrument_id: str = Field(min_length=1, max_length=160)
    market: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,15}$")
    trading_day: str = Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
    open: Decimal = Field(gt=0)
    high: Decimal = Field(gt=0)
    low: Decimal = Field(gt=0)
    close: Decimal = Field(gt=0)
    volume: Decimal = Field(ge=0)
    upstream_timestamp: AwareDatetime
    ingested_at: AwareDatetime
    frequency: str = Field(min_length=1, max_length=40)
    evidence: VersionReference
    stale: bool = False
    conflict: bool = False

    @model_validator(mode="after")
    def validate_ohlc(self) -> SimulationBar:
        if self.low > self.high:
            raise ValueError("bar low cannot exceed high")
        if not self.low <= self.open <= self.high:
            raise ValueError("bar open must be inside low/high")
        if not self.low <= self.close <= self.high:
            raise ValueError("bar close must be inside low/high")
        return self


class SimulationFill(StrictModel):
    fill_id: str = Field(min_length=1, max_length=160)
    order_id: str = Field(min_length=1, max_length=160)
    account_id: str = Field(min_length=1, max_length=160)
    instrument_id: str = Field(min_length=1, max_length=160)
    # Optional for backward compatibility with fills persisted before the
    # side field existed; new fills always carry the originating draft side.
    side: OrderSide | None = None
    quantity: Decimal = Field(gt=0)
    price: Decimal = Field(gt=0)
    fee: Decimal = Field(ge=0)
    slippage_bps: Decimal
    market_evidence: VersionReference
    model_version: str = Field(min_length=1, max_length=80)
    rule_version: str = Field(pattern=r"^simulation-rules-v[0-9]+$")
    occurred_at: AwareDatetime
    ledger_fill_id: str = Field(min_length=1, max_length=160)


class OrderTimelineEntry(StrictModel):
    """A single, evidence-backed step in an order's lifecycle.

    Entries are only produced from facts the execution store actually holds
    (draft confirmation, recorded fills, and the current order transition);
    the service never fabricates intermediate transitions it cannot prove.
    """

    status: str = Field(min_length=1, max_length=40)
    occurred_at: AwareDatetime
    actor_id: str = Field(min_length=1, max_length=160)
    detail: str | None = Field(default=None, max_length=400)


class StoredOrderView(StrictModel):
    """Read model that joins a stored order with its originating draft and fills.

    Order-level parameters (instrument, side, type, limit price, time-in-force)
    are sourced from the authoritative ``OrderDraft`` so the client receives the
    complete order regardless of exchange/fund shape.  Execution figures
    (average fill price, fee total, filled notional) are derived from recorded
    simulation fills only.
    """

    order_id: str = Field(min_length=1, max_length=160)
    owner_id: str = Field(min_length=1, max_length=160)
    order_kind: str = Field(pattern=r"^(exchange|fund)$")
    status: str = Field(min_length=1, max_length=40)
    instrument_id: str = Field(min_length=1, max_length=160)
    side: str = Field(min_length=1, max_length=40)
    order_type: str = Field(min_length=1, max_length=40)
    time_in_force: str | None = Field(default=None, max_length=40)
    limit_price: Decimal | None = Field(default=None, gt=0)
    quantity: Decimal = Field(gt=0)
    cumulative_filled: Decimal = Field(ge=0)
    remaining_quantity: Decimal = Field(ge=0)
    average_fill_price: Decimal | None = Field(default=None, gt=0)
    total_fee_rmb: Decimal = Field(ge=0)
    filled_notional_rmb: Decimal = Field(ge=0)
    revision: int = Field(ge=1)
    confirmed_at: AwareDatetime | None = None
    updated_at: AwareDatetime
    draft_reference: VersionReference
    execution_error: str | None = Field(default=None, max_length=2_000)
    fills: tuple[SimulationFill, ...] = ()
    timeline: tuple[OrderTimelineEntry, ...] = ()


class SubmissionStatus(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


class SubmissionOutcome(StrictModel):
    status: SubmissionStatus
    reason: str | None = Field(default=None, max_length=1_000)

    @model_validator(mode="after")
    def validate_reason(self) -> SubmissionOutcome:
        if self.status is SubmissionStatus.REJECTED and not self.reason:
            raise ValueError("rejected submission requires reason")
        return self


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdGenerator(Protocol):
    def new_id(self, prefix: str) -> str: ...


class AccountOwnershipPort(Protocol):
    async def require_current_account(self, owner_id: str, account_id: str) -> None: ...


class TradePlanPort(Protocol):
    async def require_executable(self, reference: VersionReference) -> None: ...


class ManualReviewPort(Protocol):
    async def review(self, draft: StoredDraft) -> ManualReviewResult: ...


class TrustedRiskPort(Protocol):
    async def evaluate(self, draft: StoredDraft) -> RiskCheckResult: ...

    async def confirm_soft(
        self,
        *,
        owner_id: str,
        result: RiskCheckResult,
        seen_reason_hash: str,
    ) -> RiskCheckResult: ...


class SubmissionTransport(Protocol):
    async def submit(self, order: StoredOrder) -> SubmissionOutcome: ...
    async def query(self, order: StoredOrder) -> SubmissionOutcome: ...
    async def cancel(self, order: StoredOrder) -> SubmissionOutcome: ...


class BarProvider(Protocol):
    async def next_bar(self, draft: OrderDraft) -> SimulationBar | None: ...


class LedgerExecutionPort(Protocol):
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
    ) -> str: ...


class ExecutionRepositoryPort(Protocol):
    async def create_draft(
        self,
        draft: StoredDraft,
        *,
        idempotency_key: str,
        request_hash: str,
    ) -> StoredDraft: ...

    async def get_draft(self, draft_id: str) -> StoredDraft | None: ...
    async def save_draft(
        self,
        draft: StoredDraft,
        *,
        expected_revision: int,
    ) -> None: ...

    async def create_order(
        self,
        order: StoredOrder,
        *,
        idempotency_key: str,
        request_hash: str,
    ) -> StoredOrder: ...

    async def get_order(self, order_id: str) -> StoredOrder | None: ...
    async def get_order_for_draft(self, draft_id: str) -> StoredOrder | None: ...
    async def save_order(
        self,
        order: StoredOrder,
        *,
        expected_revision: int,
    ) -> None: ...

    async def append_fill(self, fill: SimulationFill) -> None: ...
    async def list_fills(self, order_id: str | None = None) -> tuple[SimulationFill, ...]: ...
    async def list_orders(self, owner_id: str) -> tuple[StoredOrder, ...]: ...
