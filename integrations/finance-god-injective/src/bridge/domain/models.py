from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    computed_field,
    field_validator,
    model_validator,
)

PLAN_TTL_SECONDS = 300


class DomainError(ValueError):
    """Base error for an invalid domain operation."""


class InvalidTransitionError(DomainError):
    """Raised when a state transition is not part of the state machine."""


class RevisionConflictError(DomainError):
    """Raised when optimistic concurrency detects a stale revision."""


class PlanExpiredError(DomainError):
    """Raised when an operation requires a plan that is still valid."""


class RiskReviewMismatchError(DomainError):
    """Raised when a risk report does not describe the current plan revision."""


def utc_now() -> datetime:
    return datetime.now(UTC)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC)


UtcDateTime = Annotated[datetime, AfterValidator(_ensure_utc)]


def _parse_decimal(value: Any) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError("decimal values must be supplied as strings, integers, or Decimal")
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("invalid decimal value") from exc
    if not parsed.is_finite():
        raise ValueError("decimal value must be finite")
    return parsed


def decimal_to_string(value: Decimal) -> str:
    return format(value, "f")


DecimalValue = Annotated[
    Decimal,
    BeforeValidator(_parse_decimal),
    PlainSerializer(decimal_to_string, return_type=str, when_used="json"),
]
PositiveDecimal = Annotated[DecimalValue, Field(gt=0)]
NonNegativeDecimal = Annotated[DecimalValue, Field(ge=0)]


class DomainModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
        validate_default=True,
    )


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    LIMIT = "limit"


class TimeInForce(StrEnum):
    GTC = "gtc"


class PlanStatus(StrEnum):
    DRAFT = "draft"
    REVIEWED = "reviewed"
    CONFIRMED = "confirmed"
    SUBMITTED = "submitted"
    REJECTED = "rejected"
    EXPIRED = "expired"
    SUBMISSION_FAILED = "submission_failed"


class OrderStatus(StrEnum):
    BROADCASTING = "broadcasting"
    BROADCAST = "broadcast"
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


class MarketStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    PAUSED = "paused"


class RiskCode(StrEnum):
    PLAN_STATE = "plan_state"
    PLAN_NOT_EXPIRED = "plan_not_expired"
    ALLOWED_MARKET = "allowed_market"
    MARKET_ACTIVE = "market_active"
    SIDE_ALLOWED = "side_allowed"
    LIMIT_ORDER = "limit_order"
    GTC = "gtc"
    POSITIVE_PRICE = "positive_price"
    POSITIVE_QUANTITY = "positive_quantity"
    PRICE_TICK = "price_tick"
    QUANTITY_STEP = "quantity_step"
    MAX_NOTIONAL = "max_notional"
    ORDER_BOOK_VALID = "order_book_valid"
    PRICE_DEVIATION = "price_deviation"
    SUFFICIENT_BALANCE = "sufficient_balance"
    ACTIVE_ORDER_LIMIT = "active_order_limit"


class RiskCheck(DomainModel):
    code: RiskCode
    passed: bool
    message: str = Field(min_length=1)
    actual: str | None = None
    limit: str | None = None


class RiskReport(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    plan_id: UUID
    plan_revision: int = Field(ge=1)
    market_id: str = Field(min_length=1)
    reviewed_at: UtcDateTime = Field(default_factory=utc_now)
    notional: NonNegativeDecimal
    midpoint: NonNegativeDecimal | None = None
    checks: tuple[RiskCheck, ...] = Field(min_length=1)

    @computed_field(return_type=bool)
    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    @computed_field(return_type=tuple[RiskCode, ...])
    @property
    def violations(self) -> tuple[RiskCode, ...]:
        return tuple(check.code for check in self.checks if not check.passed)


class SourceSnapshot(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    source: Literal["finance-god"] = "finance-god"
    usage: Literal["context_only"] = "context_only"
    asset_domain: Literal["non_executable_asset_domain"] = "non_executable_asset_domain"
    plan_id: str = Field(min_length=1)
    plan_version: int = Field(ge=1)
    plan_status: str = Field(min_length=1)
    expires_at: UtcDateTime | None = None
    audit_reference: str | None = Field(default=None, min_length=1)
    draft_id: str | None = Field(default=None, min_length=1)
    draft_confirmed: bool | None = None
    normalized_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: UtcDateTime = Field(default_factory=utc_now)


class MarketSnapshot(DomainModel):
    market_id: str = Field(min_length=1)
    ticker: str = Field(min_length=1)
    status: MarketStatus
    min_price_tick_size: PositiveDecimal
    min_quantity_tick_size: PositiveDecimal
    best_bid: DecimalValue
    best_ask: DecimalValue
    observed_at: UtcDateTime = Field(default_factory=utc_now)


class AccountSnapshot(DomainModel):
    subaccount_id: str = Field(min_length=1)
    quote_available_balance: NonNegativeDecimal
    base_available_balance: NonNegativeDecimal
    observed_at: UtcDateTime = Field(default_factory=utc_now)


class RiskPolicy(DomainModel):
    allowed_market_id: str = Field(min_length=1)
    allowed_ticker: str = Field(default="INJ/USDT", min_length=1)
    max_notional: PositiveDecimal = Decimal("25")
    max_price_deviation_bps: PositiveDecimal = Decimal("100")
    max_active_orders: int = Field(default=1, ge=1)


_PLAN_TRANSITIONS: Mapping[PlanStatus, frozenset[PlanStatus]] = {
    PlanStatus.DRAFT: frozenset({PlanStatus.REVIEWED, PlanStatus.REJECTED, PlanStatus.EXPIRED}),
    PlanStatus.REVIEWED: frozenset({PlanStatus.CONFIRMED, PlanStatus.REJECTED, PlanStatus.EXPIRED}),
    PlanStatus.CONFIRMED: frozenset(
        {
            PlanStatus.SUBMITTED,
            PlanStatus.SUBMISSION_FAILED,
            PlanStatus.EXPIRED,
        }
    ),
    PlanStatus.SUBMITTED: frozenset(),
    PlanStatus.REJECTED: frozenset(),
    PlanStatus.EXPIRED: frozenset(),
    PlanStatus.SUBMISSION_FAILED: frozenset(),
}


class InjectivePlan(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    market_id: str = Field(min_length=1)
    ticker: str = Field(min_length=1)
    side: Side
    order_type: OrderType = OrderType.LIMIT
    time_in_force: TimeInForce = TimeInForce.GTC
    price: PositiveDecimal
    quantity: PositiveDecimal
    source_snapshot_id: UUID | None = None
    status: PlanStatus = PlanStatus.DRAFT
    revision: int = Field(default=1, ge=1)
    risk_report: RiskReport | None = None
    created_at: UtcDateTime = Field(default_factory=utc_now)
    updated_at: UtcDateTime | None = None
    expires_at: UtcDateTime | None = None

    @model_validator(mode="after")
    def validate_timestamps(self) -> InjectivePlan:
        updated_at = self.updated_at or self.created_at
        expires_at = self.expires_at or (self.created_at + timedelta(seconds=PLAN_TTL_SECONDS))
        if updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        if expires_at <= self.created_at:
            raise ValueError("expires_at must follow created_at")
        object.__setattr__(self, "updated_at", updated_at)
        object.__setattr__(self, "expires_at", expires_at)
        return self

    def is_expired(self, at: datetime | None = None) -> bool:
        checked_at = _ensure_utc(at or utc_now())
        assert self.expires_at is not None
        return checked_at >= self.expires_at

    def apply_review(self, report: RiskReport) -> InjectivePlan:
        if report.plan_id != self.id or report.plan_revision != self.revision:
            raise RiskReviewMismatchError("risk report must match the current plan revision")
        if report.market_id != self.market_id:
            raise RiskReviewMismatchError("risk report market does not match plan")
        if self.status is not PlanStatus.DRAFT:
            raise InvalidTransitionError("only a draft plan can be reviewed")

        target = PlanStatus.REVIEWED if report.passed else PlanStatus.REJECTED
        if self.is_expired(report.reviewed_at):
            target = PlanStatus.EXPIRED
        return self._transition(target, report.reviewed_at, risk_report=report)

    def confirm(
        self,
        *,
        expected_revision: int,
        at: datetime | None = None,
    ) -> InjectivePlan:
        confirmed_at = _ensure_utc(at or utc_now())
        self._check_revision(expected_revision)
        if self.is_expired(confirmed_at):
            raise PlanExpiredError("plan has expired")
        return self._transition(PlanStatus.CONFIRMED, confirmed_at)

    def mark_submitted(
        self,
        *,
        expected_revision: int,
        at: datetime | None = None,
    ) -> InjectivePlan:
        submitted_at = _ensure_utc(at or utc_now())
        self._check_revision(expected_revision)
        if self.is_expired(submitted_at):
            raise PlanExpiredError("plan has expired")
        return self._transition(PlanStatus.SUBMITTED, submitted_at)

    def mark_submission_failed(
        self,
        *,
        expected_revision: int,
        at: datetime | None = None,
    ) -> InjectivePlan:
        self._check_revision(expected_revision)
        return self._transition(PlanStatus.SUBMISSION_FAILED, at or utc_now())

    def expire(
        self,
        *,
        expected_revision: int,
        at: datetime | None = None,
    ) -> InjectivePlan:
        expired_at = _ensure_utc(at or utc_now())
        self._check_revision(expected_revision)
        if not self.is_expired(expired_at):
            raise PlanExpiredError("plan is not expired yet")
        return self._transition(PlanStatus.EXPIRED, expired_at)

    def _check_revision(self, expected_revision: int) -> None:
        if self.revision != expected_revision:
            raise RevisionConflictError(
                f"expected revision {expected_revision}, found {self.revision}"
            )

    def _transition(
        self,
        target: PlanStatus,
        at: datetime,
        *,
        risk_report: RiskReport | None = None,
    ) -> InjectivePlan:
        transitioned_at = _ensure_utc(at)
        if target not in _PLAN_TRANSITIONS[self.status]:
            raise InvalidTransitionError(
                f"plan cannot transition from {self.status.value} to {target.value}"
            )
        return InjectivePlan.model_validate(
            {
                **self.model_dump(exclude={"risk_report"}),
                "status": target,
                "revision": self.revision + 1,
                "risk_report": risk_report or self.risk_report,
                "updated_at": transitioned_at,
            }
        )


_ORDER_TRANSITIONS: Mapping[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.BROADCASTING: frozenset(
        {OrderStatus.BROADCAST, OrderStatus.REJECTED, OrderStatus.UNKNOWN}
    ),
    OrderStatus.BROADCAST: frozenset(
        {
            OrderStatus.OPEN,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.UNKNOWN,
        }
    ),
    OrderStatus.OPEN: frozenset(
        {
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.UNKNOWN,
        }
    ),
    OrderStatus.PARTIALLY_FILLED: frozenset(
        {
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.UNKNOWN,
        }
    ),
    OrderStatus.UNKNOWN: frozenset(
        {
            OrderStatus.BROADCAST,
            OrderStatus.OPEN,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
        }
    ),
    OrderStatus.FILLED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
    OrderStatus.REJECTED: frozenset(),
}

ACTIVE_ORDER_STATUSES = frozenset(
    {
        OrderStatus.BROADCASTING,
        OrderStatus.BROADCAST,
        OrderStatus.OPEN,
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.UNKNOWN,
    }
)


class InjectiveOrder(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    plan_id: UUID
    market_id: str = Field(min_length=1)
    subaccount_id: str = Field(min_length=1)
    quantity: PositiveDecimal
    filled_quantity: NonNegativeDecimal = Decimal("0")
    status: OrderStatus = OrderStatus.BROADCASTING
    revision: int = Field(default=1, ge=1)
    tx_hash: str | None = Field(default=None, min_length=1)
    order_hash: str | None = Field(default=None, min_length=1)
    created_at: UtcDateTime = Field(default_factory=utc_now)
    updated_at: UtcDateTime | None = None

    @model_validator(mode="after")
    def validate_order(self) -> InjectiveOrder:
        updated_at = self.updated_at or self.created_at
        if updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        if self.filled_quantity > self.quantity:
            raise ValueError("filled quantity cannot exceed order quantity")
        if self.status is OrderStatus.BROADCAST and not self.tx_hash:
            raise ValueError("broadcast order requires tx_hash")
        if (
            self.status
            in {
                OrderStatus.OPEN,
                OrderStatus.PARTIALLY_FILLED,
                OrderStatus.FILLED,
                OrderStatus.CANCELLED,
            }
            and not self.order_hash
        ):
            raise ValueError(f"{self.status.value} order requires order_hash")
        if self.status is OrderStatus.PARTIALLY_FILLED and not (
            Decimal("0") < self.filled_quantity < self.quantity
        ):
            raise ValueError("partially filled order requires a partial fill")
        if self.status is OrderStatus.FILLED and self.filled_quantity != self.quantity:
            raise ValueError("filled order requires the full quantity")
        object.__setattr__(self, "updated_at", updated_at)
        return self

    @computed_field(return_type=bool)
    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_ORDER_STATUSES

    def transition(
        self,
        target: OrderStatus,
        *,
        expected_revision: int,
        tx_hash: str | None = None,
        order_hash: str | None = None,
        filled_quantity: Decimal | str | int | None = None,
        at: datetime | None = None,
    ) -> InjectiveOrder:
        if self.revision != expected_revision:
            raise RevisionConflictError(
                f"expected revision {expected_revision}, found {self.revision}"
            )
        if target not in _ORDER_TRANSITIONS[self.status]:
            raise InvalidTransitionError(
                f"order cannot transition from {self.status.value} to {target.value}"
            )

        next_filled = (
            self.filled_quantity if filled_quantity is None else _parse_decimal(filled_quantity)
        )
        if next_filled < self.filled_quantity:
            raise DomainError("filled quantity cannot decrease")
        if (
            self.status is OrderStatus.PARTIALLY_FILLED
            and target is OrderStatus.PARTIALLY_FILLED
            and next_filled == self.filled_quantity
        ):
            raise DomainError("partial fill update must increase filled quantity")
        return InjectiveOrder.model_validate(
            {
                **self.model_dump(exclude={"is_active"}),
                "status": target,
                "revision": self.revision + 1,
                "tx_hash": tx_hash or self.tx_hash,
                "order_hash": order_hash or self.order_hash,
                "filled_quantity": next_filled,
                "updated_at": _ensure_utc(at or utc_now()),
            }
        )


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


class OrderEvent(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    order_id: UUID
    event_key: str = Field(min_length=1)
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: OrderStatus
    payload_json: str = Field(min_length=2)
    occurred_at: UtcDateTime
    observed_at: UtcDateTime = Field(default_factory=utc_now)

    @field_validator("payload_json")
    @classmethod
    def validate_payload_json(cls, value: str) -> str:
        parsed = json.loads(value)
        if not isinstance(parsed, dict):
            raise ValueError("event payload must be a JSON object")
        return _canonical_json(parsed)

    @model_validator(mode="after")
    def validate_payload_hash(self) -> OrderEvent:
        digest = hashlib.sha256(self.payload_json.encode("utf-8")).hexdigest()
        if digest != self.payload_hash:
            raise ValueError("payload_hash does not match payload_json")
        return self

    @classmethod
    def from_payload(
        cls,
        *,
        order_id: UUID,
        event_key: str,
        status: OrderStatus,
        payload: Mapping[str, Any],
        occurred_at: datetime,
        observed_at: datetime | None = None,
    ) -> OrderEvent:
        payload_json = _canonical_json(payload)
        return cls(
            order_id=order_id,
            event_key=event_key,
            payload_hash=hashlib.sha256(payload_json.encode("utf-8")).hexdigest(),
            status=status,
            payload_json=payload_json,
            occurred_at=occurred_at,
            observed_at=observed_at or utc_now(),
        )
