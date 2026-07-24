from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Literal, Self

from pydantic import AwareDatetime, Field, field_validator, model_validator

from .errors import DomainInvariantViolation
from .models import FrozenModel, VersionReference
from .simulation_rules import SIMULATION_RULE_VERSION, derived_money

ZERO = Decimal("0")
MONEY_QUANTUM = Decimal("0.00000001")
QUANTITY_QUANTUM = Decimal("0.000000000001")
RATE_QUANTUM = QUANTITY_QUANTUM
CNY = "CNY"


def canonical_decimal(value: Decimal, quantum: Decimal, field_name: str) -> Decimal:
    if not value.is_finite():
        raise DomainInvariantViolation(f"{field_name} must be finite")
    if value.is_zero():
        return ZERO.quantize(quantum)
    try:
        quantized = value.quantize(quantum)
    except InvalidOperation as exc:
        raise DomainInvariantViolation(f"{field_name} exceeds supported precision") from exc
    if quantized != value:
        exponent = quantum.as_tuple().exponent
        if not isinstance(exponent, int):
            raise DomainInvariantViolation(f"{field_name} has an invalid quantum")
        raise DomainInvariantViolation(
            f"{field_name} exceeds {abs(exponent)} decimal places"
        )
    return quantized


def canonical_money(value: Decimal, field_name: str) -> Decimal:
    return canonical_decimal(value, MONEY_QUANTUM, field_name)


def canonical_quantity(value: Decimal, field_name: str) -> Decimal:
    return canonical_decimal(value, QUANTITY_QUANTUM, field_name)


def canonical_rate(value: Decimal, field_name: str) -> Decimal:
    return canonical_decimal(value, RATE_QUANTUM, field_name)


def canonical_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DomainInvariantViolation("datetime must be timezone-aware")
    return value.astimezone(timezone.utc)


def canonical_hash(value: object) -> str:
    encoded = json.dumps(
        _canonical(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def validated_replace(model: FrozenModel, **updates: object) -> object:
    values = model.model_dump(mode="python")
    values.update(updates)
    return type(model).model_validate(values)


class Money(FrozenModel):
    currency: str = Field(pattern=r"^[A-Z]{3}$", min_length=3, max_length=3)
    amount: Decimal

    @field_validator("amount")
    @classmethod
    def normalize_amount(cls, value: Decimal) -> Decimal:
        return canonical_money(value, "money.amount")


class ExchangeRateEvidence(FrozenModel):
    base_currency: str = Field(pattern=r"^[A-Z]{3}$", min_length=3, max_length=3)
    quote_currency: str = Field(pattern=r"^[A-Z]{3}$", min_length=3, max_length=3)
    rate: Decimal = Field(gt=0)
    observed_at: AwareDatetime
    source: VersionReference

    @field_validator("rate")
    @classmethod
    def normalize_rate(cls, value: Decimal) -> Decimal:
        return canonical_rate(value, "exchange_rate")

    @field_validator("observed_at")
    @classmethod
    def normalize_observed_at(cls, value: datetime) -> datetime:
        return canonical_utc(value)

    @model_validator(mode="after")
    def validate_pair(self) -> Self:
        if self.base_currency == self.quote_currency:
            raise DomainInvariantViolation("FX evidence requires distinct currencies")
        if self.quote_currency != CNY:
            raise DomainInvariantViolation("FX evidence quote currency must be CNY")
        return self


class ReservationKind(str, Enum):
    CASH_BUY = "cash_buy"
    CASH_COVER = "cash_cover"
    SHORT_MARGIN = "short_margin"
    FUND_SUBSCRIPTION = "fund_subscription"
    FUND_REDEMPTION = "fund_redemption"


class TradeSide(str, Enum):
    BUY = "buy"
    SELL = "sell"
    SHORT = "short"
    COVER = "cover"


class FundAction(str, Enum):
    SUBSCRIBE = "subscribe"
    REDEEM = "redeem"


class AccountOpenedPayload(FrozenModel):
    kind: Literal["account_opened"] = "account_opened"
    initial_cash: Money

    @model_validator(mode="after")
    def validate_opening(self) -> Self:
        if self.initial_cash.currency != CNY or self.initial_cash.amount <= ZERO:
            raise DomainInvariantViolation("account opening requires positive CNY cash")
        return self


class AccountResetClosedPayload(FrozenModel):
    kind: Literal["account_reset_closed"] = "account_reset_closed"
    new_account_id: str = Field(min_length=1, max_length=160)


class CashReservedPayload(FrozenModel):
    kind: Literal["cash_reserved"] = "cash_reserved"
    reservation_id: str = Field(min_length=1, max_length=160)
    order_id: str = Field(min_length=1, max_length=160)
    instrument_id: str = Field(min_length=1, max_length=160)
    reservation_kind: ReservationKind
    native_amount: Money
    rmb_amount: Money
    exchange_rate: ExchangeRateEvidence | None = None

    @model_validator(mode="after")
    def validate_reservation(self) -> Self:
        _require_positive(self.native_amount, "native reservation")
        _require_positive_rmb(self.rmb_amount, "RMB reservation")
        _validate_fx(self.native_amount, self.rmb_amount, self.exchange_rate)
        if self.reservation_kind is ReservationKind.FUND_REDEMPTION:
            raise DomainInvariantViolation("fund redemption reserves position, not cash")
        return self


class CashReleasedPayload(FrozenModel):
    kind: Literal["cash_released"] = "cash_released"
    reservation_id: str = Field(min_length=1, max_length=160)
    order_id: str = Field(min_length=1, max_length=160)
    native_amount: Money
    rmb_amount: Money

    @model_validator(mode="after")
    def validate_release(self) -> Self:
        _require_positive(self.native_amount, "native release")
        _require_positive_rmb(self.rmb_amount, "RMB release")
        return self


class PositionReservedPayload(FrozenModel):
    kind: Literal["position_reserved"] = "position_reserved"
    reservation_id: str = Field(min_length=1, max_length=160)
    order_id: str = Field(min_length=1, max_length=160)
    instrument_id: str = Field(min_length=1, max_length=160)
    quantity: Decimal = Field(gt=0)

    @field_validator("quantity")
    @classmethod
    def normalize_quantity(cls, value: Decimal) -> Decimal:
        return canonical_quantity(value, "position reservation quantity")


class TradeFillPayload(FrozenModel):
    kind: Literal["trade_fill"] = "trade_fill"
    side: TradeSide
    reservation_id: str | None = Field(default=None, max_length=160)
    order_id: str = Field(min_length=1, max_length=160)
    instrument_id: str = Field(min_length=1, max_length=160)
    quantity: Decimal = Field(gt=0)
    native_gross: Money
    native_fee: Money
    native_borrow_fee: Money
    rmb_gross: Money
    rmb_fee: Money
    rmb_borrow_fee: Money
    margin_change_rmb: Money
    exchange_rate: ExchangeRateEvidence | None = None
    slippage_bps: Decimal
    market_evidence: VersionReference
    model_version: str = Field(min_length=1, max_length=80)

    @field_validator("quantity")
    @classmethod
    def normalize_quantity(cls, value: Decimal) -> Decimal:
        return canonical_quantity(value, "fill quantity")

    @field_validator("slippage_bps")
    @classmethod
    def normalize_slippage(cls, value: Decimal) -> Decimal:
        return canonical_rate(value, "slippage_bps")

    @model_validator(mode="after")
    def validate_trade(self) -> Self:
        currencies = {
            self.native_gross.currency,
            self.native_fee.currency,
            self.native_borrow_fee.currency,
        }
        if len(currencies) != 1:
            raise DomainInvariantViolation("native fill amounts must share currency")
        for amount, label in (
            (self.native_gross, "native gross"),
            (self.rmb_gross, "RMB gross"),
        ):
            _require_positive(amount, label)
        for amount, label in (
            (self.native_fee, "native fee"),
            (self.native_borrow_fee, "native borrow fee"),
            (self.rmb_fee, "RMB fee"),
            (self.rmb_borrow_fee, "RMB borrow fee"),
        ):
            _require_nonnegative(amount, label)
        for amount in (
            self.rmb_gross,
            self.rmb_fee,
            self.rmb_borrow_fee,
            self.margin_change_rmb,
        ):
            if amount.currency != CNY:
                raise DomainInvariantViolation("RMB fill facts must use CNY")
        _validate_fx(self.native_gross, self.rmb_gross, self.exchange_rate)
        _validate_converted(self.native_fee, self.rmb_fee, self.exchange_rate)
        _validate_converted(
            self.native_borrow_fee, self.rmb_borrow_fee, self.exchange_rate
        )
        if self.side in {TradeSide.BUY, TradeSide.COVER} and not self.reservation_id:
            raise DomainInvariantViolation("buy and cover fills require a reservation")
        if self.side is TradeSide.SHORT and self.margin_change_rmb.amount <= ZERO:
            raise DomainInvariantViolation("short fill requires positive margin")
        if self.side is TradeSide.COVER and self.margin_change_rmb.amount > ZERO:
            raise DomainInvariantViolation("cover cannot increase margin")
        if self.side in {TradeSide.BUY, TradeSide.SELL} and (
            self.margin_change_rmb.amount != ZERO
        ):
            raise DomainInvariantViolation("long trades cannot change short margin")
        return self


class FundFillPayload(FrozenModel):
    kind: Literal["fund_fill"] = "fund_fill"
    action: FundAction
    reservation_id: str = Field(min_length=1, max_length=160)
    order_id: str = Field(min_length=1, max_length=160)
    instrument_id: str = Field(min_length=1, max_length=160)
    units: Decimal = Field(gt=0)
    nav: Money
    native_gross: Money
    native_fee: Money
    rmb_gross: Money
    rmb_fee: Money
    exchange_rate: ExchangeRateEvidence | None = None
    market_evidence: VersionReference
    model_version: str = Field(min_length=1, max_length=80)
    settled: bool

    @field_validator("units")
    @classmethod
    def normalize_units(cls, value: Decimal) -> Decimal:
        return canonical_quantity(value, "fund units")

    @model_validator(mode="after")
    def validate_fund(self) -> Self:
        if self.nav.currency != self.native_gross.currency:
            raise DomainInvariantViolation("fund NAV and gross currency must match")
        _require_positive(self.nav, "fund NAV")
        _require_positive(self.native_gross, "fund gross")
        _require_positive_rmb(self.rmb_gross, "fund RMB gross")
        _require_nonnegative(self.native_fee, "fund fee")
        _require_nonnegative(self.rmb_fee, "fund RMB fee")
        _validate_fx(self.native_gross, self.rmb_gross, self.exchange_rate)
        _validate_converted(self.native_fee, self.rmb_fee, self.exchange_rate)
        return self


class ReversalPayload(FrozenModel):
    kind: Literal["reversal"] = "reversal"
    original_event_id: str = Field(min_length=1, max_length=160)
    original_event_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=500)


EventPayload = (
    AccountOpenedPayload
    | AccountResetClosedPayload
    | CashReservedPayload
    | CashReleasedPayload
    | PositionReservedPayload
    | TradeFillPayload
    | FundFillPayload
    | ReversalPayload
)


class AccountEventType(str, Enum):
    ACCOUNT_OPENED = "account_opened"
    ACCOUNT_RESET_CLOSED = "account_reset_closed"
    CASH_RESERVED = "cash_reserved"
    CASH_RELEASED = "cash_released"
    POSITION_RESERVED = "position_reserved"
    BUY_FILL_RECORDED = "buy_fill_recorded"
    SELL_FILL_RECORDED = "sell_fill_recorded"
    SHORT_FILL_RECORDED = "short_fill_recorded"
    COVER_FILL_RECORDED = "cover_fill_recorded"
    FUND_SUBSCRIPTION_CONFIRMED = "fund_subscription_confirmed"
    FUND_REDEMPTION_CONFIRMED = "fund_redemption_confirmed"
    REVERSAL_RECORDED = "reversal_recorded"


PAYLOAD_EVENT_TYPES: dict[str, frozenset[AccountEventType]] = {
    "account_opened": frozenset({AccountEventType.ACCOUNT_OPENED}),
    "account_reset_closed": frozenset({AccountEventType.ACCOUNT_RESET_CLOSED}),
    "cash_reserved": frozenset({AccountEventType.CASH_RESERVED}),
    "cash_released": frozenset({AccountEventType.CASH_RELEASED}),
    "position_reserved": frozenset({AccountEventType.POSITION_RESERVED}),
    "trade_fill": frozenset(
        {
            AccountEventType.BUY_FILL_RECORDED,
            AccountEventType.SELL_FILL_RECORDED,
            AccountEventType.SHORT_FILL_RECORDED,
            AccountEventType.COVER_FILL_RECORDED,
        }
    ),
    "fund_fill": frozenset(
        {
            AccountEventType.FUND_SUBSCRIPTION_CONFIRMED,
            AccountEventType.FUND_REDEMPTION_CONFIRMED,
        }
    ),
    "reversal": frozenset({AccountEventType.REVERSAL_RECORDED}),
}


class AccountEventEnvelope(FrozenModel):
    event_id: str = Field(min_length=1, max_length=160)
    account_id: str = Field(min_length=1, max_length=160)
    owner_user_id: str = Field(min_length=1, max_length=160)
    sequence: int = Field(ge=1)
    event_type: AccountEventType
    occurred_at: AwareDatetime
    correlation_id: str = Field(min_length=1, max_length=160)
    causation_id: str = Field(min_length=1, max_length=160)
    source: VersionReference
    rule_version: str = Field(pattern=r"^simulation-rules-v[0-9]+$")
    previous_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    payload: EventPayload
    event_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("occurred_at")
    @classmethod
    def normalize_occurred_at(cls, value: datetime) -> datetime:
        return canonical_utc(value)

    @classmethod
    def create(cls, **values: object) -> AccountEventEnvelope:
        values["event_hash"] = canonical_hash(values)
        return cls.model_validate(values)

    @model_validator(mode="after")
    def validate_event(self) -> Self:
        if self.event_type not in PAYLOAD_EVENT_TYPES[self.payload.kind]:
            raise DomainInvariantViolation("event type does not match payload")
        if isinstance(self.payload, TradeFillPayload):
            expected = {
                TradeSide.BUY: AccountEventType.BUY_FILL_RECORDED,
                TradeSide.SELL: AccountEventType.SELL_FILL_RECORDED,
                TradeSide.SHORT: AccountEventType.SHORT_FILL_RECORDED,
                TradeSide.COVER: AccountEventType.COVER_FILL_RECORDED,
            }[self.payload.side]
            if self.event_type is not expected:
                raise DomainInvariantViolation("trade side does not match event type")
        if isinstance(self.payload, FundFillPayload):
            expected = (
                AccountEventType.FUND_SUBSCRIPTION_CONFIRMED
                if self.payload.action is FundAction.SUBSCRIBE
                else AccountEventType.FUND_REDEMPTION_CONFIRMED
            )
            if self.event_type is not expected:
                raise DomainInvariantViolation("fund action does not match event type")
        values = self.model_dump(mode="python", exclude={"event_hash"})
        if self.event_hash != canonical_hash(values):
            raise DomainInvariantViolation("event_hash does not match event contents")
        return self


class LedgerPosting(FrozenModel):
    posting_id: str = Field(min_length=1, max_length=160)
    sequence: int = Field(ge=1)
    account_code: str = Field(min_length=1, max_length=80)
    original: Money
    rmb_amount: Decimal
    posting_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("rmb_amount")
    @classmethod
    def normalize_rmb(cls, value: Decimal) -> Decimal:
        return canonical_money(value, "posting.rmb_amount")

    @classmethod
    def create(cls, **values: object) -> LedgerPosting:
        values["posting_hash"] = canonical_hash(values)
        return cls.model_validate(values)

    @model_validator(mode="after")
    def validate_hash(self) -> Self:
        values = self.model_dump(mode="python", exclude={"posting_hash"})
        if self.posting_hash != canonical_hash(values):
            raise DomainInvariantViolation("posting_hash does not match posting")
        return self


class JournalEntry(FrozenModel):
    journal_id: str = Field(min_length=1, max_length=160)
    account_id: str = Field(min_length=1, max_length=160)
    event_id: str = Field(min_length=1, max_length=160)
    occurred_at: AwareDatetime
    rule_version: str = Field(pattern=r"^simulation-rules-v[0-9]+$")
    reversal_of_journal_id: str | None = Field(default=None, max_length=160)
    postings: tuple[LedgerPosting, ...] = Field(min_length=2)
    journal_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("occurred_at")
    @classmethod
    def normalize_occurred_at(cls, value: datetime) -> datetime:
        return canonical_utc(value)

    @classmethod
    def create(cls, **values: object) -> JournalEntry:
        values.setdefault("reversal_of_journal_id", None)
        values["journal_hash"] = canonical_hash(values)
        return cls.model_validate(values)

    @model_validator(mode="after")
    def require_balanced_postings(self) -> Self:
        sequences = tuple(posting.sequence for posting in self.postings)
        if sequences != tuple(range(1, len(self.postings) + 1)):
            raise DomainInvariantViolation(
                "journal posting sequences must be contiguous from one"
            )
        if sum((posting.rmb_amount for posting in self.postings), ZERO) != ZERO:
            raise DomainInvariantViolation("journal RMB postings must balance")
        for currency in {posting.original.currency for posting in self.postings}:
            total = sum(
                (
                    posting.original.amount
                    for posting in self.postings
                    if posting.original.currency == currency
                ),
                ZERO,
            )
            if total != ZERO:
                raise DomainInvariantViolation(
                    f"journal {currency} postings must balance"
                )
        values = self.model_dump(mode="python", exclude={"journal_hash"})
        if self.journal_hash != canonical_hash(values):
            raise DomainInvariantViolation("journal_hash does not match journal")
        return self


class CashProjection(FrozenModel):
    account_id: str = Field(min_length=1, max_length=160)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    total: Decimal = ZERO
    frozen: Decimal = ZERO
    margin: Decimal = ZERO
    rmb_total: Decimal = ZERO
    rmb_frozen: Decimal = ZERO
    rmb_margin: Decimal = ZERO
    revision: int = Field(default=0, ge=0)

    @field_validator(
        "total", "frozen", "margin", "rmb_total", "rmb_frozen", "rmb_margin"
    )
    @classmethod
    def normalize_money(cls, value: Decimal, info: object) -> Decimal:
        return canonical_money(value, "cash projection")

    @property
    def available(self) -> Decimal:
        return self.total - self.frozen - self.margin

    @property
    def rmb_available(self) -> Decimal:
        return self.rmb_total - self.rmb_frozen - self.rmb_margin

    @model_validator(mode="after")
    def validate_cash(self) -> Self:
        values = (
            self.total,
            self.frozen,
            self.margin,
            self.rmb_total,
            self.rmb_frozen,
            self.rmb_margin,
        )
        if any(value < ZERO for value in values):
            raise DomainInvariantViolation("cash projection cannot be negative")
        if self.frozen + self.margin > self.total:
            raise DomainInvariantViolation("native cash allocations exceed total")
        if self.rmb_frozen + self.rmb_margin > self.rmb_total:
            raise DomainInvariantViolation("RMB cash allocations exceed total")
        if self.currency == CNY and (
            self.total != self.rmb_total
            or self.frozen != self.rmb_frozen
            or self.margin != self.rmb_margin
        ):
            raise DomainInvariantViolation("CNY native and RMB projections must match")
        return self


class PositionProjection(FrozenModel):
    account_id: str = Field(min_length=1, max_length=160)
    instrument_id: str = Field(min_length=1, max_length=160)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    long_quantity: Decimal = ZERO
    short_quantity: Decimal = ZERO
    settled_quantity: Decimal = ZERO
    frozen_quantity: Decimal = ZERO
    long_cost_native: Decimal = ZERO
    long_cost_rmb: Decimal = ZERO
    short_proceeds_native: Decimal = ZERO
    short_proceeds_rmb: Decimal = ZERO
    margin_rmb: Decimal = ZERO
    borrow_fee_rmb: Decimal = ZERO
    revision: int = Field(default=0, ge=0)

    @field_validator(
        "long_quantity", "short_quantity", "settled_quantity", "frozen_quantity"
    )
    @classmethod
    def normalize_quantities(cls, value: Decimal) -> Decimal:
        return canonical_quantity(value, "position quantity")

    @field_validator(
        "long_cost_native",
        "long_cost_rmb",
        "short_proceeds_native",
        "short_proceeds_rmb",
        "margin_rmb",
        "borrow_fee_rmb",
    )
    @classmethod
    def normalize_amounts(cls, value: Decimal) -> Decimal:
        return canonical_money(value, "position amount")

    @model_validator(mode="after")
    def validate_position(self) -> Self:
        values = (
            self.long_quantity,
            self.short_quantity,
            self.settled_quantity,
            self.frozen_quantity,
            self.long_cost_native,
            self.long_cost_rmb,
            self.short_proceeds_native,
            self.short_proceeds_rmb,
            self.margin_rmb,
            self.borrow_fee_rmb,
        )
        if any(value < ZERO for value in values):
            raise DomainInvariantViolation("position facts cannot be negative")
        if self.frozen_quantity > self.settled_quantity:
            raise DomainInvariantViolation("frozen quantity exceeds settled quantity")
        if self.settled_quantity > self.long_quantity:
            raise DomainInvariantViolation("settled quantity exceeds long quantity")
        if self.short_quantity == ZERO and any(
            value != ZERO
            for value in (
                self.short_proceeds_native,
                self.short_proceeds_rmb,
                self.margin_rmb,
                self.borrow_fee_rmb,
            )
        ):
            raise DomainInvariantViolation(
                "closed short position cannot retain proceeds, margin, or borrow fees"
            )
        return self


class ReservationStatus(str, Enum):
    ACTIVE = "active"
    RELEASED = "released"
    CONSUMED = "consumed"


class Reservation(FrozenModel):
    reservation_id: str = Field(min_length=1, max_length=160)
    account_id: str = Field(min_length=1, max_length=160)
    order_id: str = Field(min_length=1, max_length=160)
    instrument_id: str = Field(min_length=1, max_length=160)
    kind: ReservationKind
    native_amount: Money
    rmb_amount: Decimal
    quantity: Decimal = ZERO
    consumed_native: Decimal = ZERO
    consumed_rmb: Decimal = ZERO
    consumed_quantity: Decimal = ZERO
    status: ReservationStatus = ReservationStatus.ACTIVE
    revision: int = Field(default=1, ge=1)

    @field_validator("rmb_amount", "consumed_native", "consumed_rmb")
    @classmethod
    def normalize_amounts(cls, value: Decimal) -> Decimal:
        return canonical_money(value, "reservation amount")

    @field_validator("quantity", "consumed_quantity")
    @classmethod
    def normalize_quantities(cls, value: Decimal) -> Decimal:
        return canonical_quantity(value, "reservation quantity")

    @property
    def remaining_native(self) -> Decimal:
        return self.native_amount.amount - self.consumed_native

    @property
    def remaining_rmb(self) -> Decimal:
        return self.rmb_amount - self.consumed_rmb

    @property
    def remaining_quantity(self) -> Decimal:
        return self.quantity - self.consumed_quantity

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        if any(
            value < ZERO
            for value in (
                self.rmb_amount,
                self.quantity,
                self.consumed_native,
                self.consumed_rmb,
                self.consumed_quantity,
            )
        ):
            raise DomainInvariantViolation("reservation facts cannot be negative")
        if self.consumed_native > self.native_amount.amount:
            raise DomainInvariantViolation("native reservation over-consumed")
        if self.consumed_rmb > self.rmb_amount:
            raise DomainInvariantViolation("RMB reservation over-consumed")
        if self.consumed_quantity > self.quantity:
            raise DomainInvariantViolation("position reservation over-consumed")
        complete = (
            (
                self.rmb_amount > ZERO
                and self.consumed_rmb == self.rmb_amount
                and self.consumed_native == self.native_amount.amount
            )
            or (
                self.quantity > ZERO
                and self.consumed_quantity == self.quantity
            )
        )
        if self.status is ReservationStatus.CONSUMED and not complete:
            raise DomainInvariantViolation("consumed reservation must be fully consumed")
        if self.status is ReservationStatus.ACTIVE and complete:
            raise DomainInvariantViolation("fully consumed reservation cannot be active")
        return self

    def consume_cash(
        self,
        *,
        order_id: str,
        instrument_id: str,
        expected_kind: ReservationKind,
        native_amount: Decimal,
        rmb_amount: Decimal,
    ) -> Reservation:
        self.require_binding(
            order_id=order_id,
            instrument_id=instrument_id,
            expected_kind=expected_kind,
        )
        if self.status is not ReservationStatus.ACTIVE:
            raise DomainInvariantViolation("only active reservations can be consumed")
        next_native = self.consumed_native + canonical_money(
            native_amount, "consumed native"
        )
        next_rmb = self.consumed_rmb + canonical_money(rmb_amount, "consumed RMB")
        status = (
            ReservationStatus.CONSUMED
            if next_native == self.native_amount.amount and next_rmb == self.rmb_amount
            else ReservationStatus.ACTIVE
        )
        return Reservation.model_validate(
            {
                **self.model_dump(mode="python"),
                "consumed_native": next_native,
                "consumed_rmb": next_rmb,
                "status": status,
                "revision": self.revision + 1,
            }
        )

    def consume_position(
        self,
        quantity: Decimal,
        *,
        order_id: str,
        instrument_id: str,
        expected_kind: ReservationKind,
    ) -> Reservation:
        self.require_binding(
            order_id=order_id,
            instrument_id=instrument_id,
            expected_kind=expected_kind,
        )
        if self.status is not ReservationStatus.ACTIVE:
            raise DomainInvariantViolation("only active reservations can be consumed")
        next_quantity = self.consumed_quantity + canonical_quantity(
            quantity, "consumed quantity"
        )
        status = (
            ReservationStatus.CONSUMED
            if next_quantity == self.quantity
            else ReservationStatus.ACTIVE
        )
        return Reservation.model_validate(
            {
                **self.model_dump(mode="python"),
                "consumed_quantity": next_quantity,
                "status": status,
                "revision": self.revision + 1,
            }
        )

    def require_binding(
        self,
        *,
        order_id: str,
        instrument_id: str,
        expected_kind: ReservationKind,
    ) -> None:
        if self.order_id != order_id:
            raise DomainInvariantViolation("reservation order does not match command")
        if self.instrument_id != instrument_id:
            raise DomainInvariantViolation("reservation instrument does not match command")
        if self.kind is not expected_kind:
            raise DomainInvariantViolation("reservation kind does not match operation")

    def release(self) -> Reservation:
        if self.status is not ReservationStatus.ACTIVE:
            raise DomainInvariantViolation("only active reservations can be released")
        return Reservation.model_validate(
            {
                **self.model_dump(mode="python"),
                "status": ReservationStatus.RELEASED,
                "revision": self.revision + 1,
            }
        )


class Fill(FrozenModel):
    fill_id: str = Field(min_length=1, max_length=160)
    event_id: str = Field(min_length=1, max_length=160)
    account_id: str = Field(min_length=1, max_length=160)
    order_id: str = Field(min_length=1, max_length=160)
    reservation_id: str | None = Field(default=None, max_length=160)
    instrument_id: str = Field(min_length=1, max_length=160)
    transaction_type: str = Field(min_length=1, max_length=40)
    quantity: Decimal = Field(gt=0)
    native_gross: Money
    native_fee: Money
    native_borrow_fee: Money
    rmb_gross: Decimal
    rmb_fee: Decimal
    rmb_borrow_fee: Decimal
    margin_change_rmb: Decimal
    slippage_bps: Decimal
    exchange_rate: ExchangeRateEvidence | None
    market_evidence: VersionReference
    model_version: str = Field(min_length=1, max_length=80)
    rule_version: str = Field(pattern=r"^simulation-rules-v[0-9]+$")
    occurred_at: AwareDatetime

    @field_validator("quantity")
    @classmethod
    def normalize_quantity(cls, value: Decimal) -> Decimal:
        return canonical_quantity(value, "fill.quantity")

    @field_validator(
        "rmb_gross", "rmb_fee", "rmb_borrow_fee", "margin_change_rmb"
    )
    @classmethod
    def normalize_amounts(cls, value: Decimal) -> Decimal:
        return canonical_money(value, "fill amount")

    @field_validator("slippage_bps")
    @classmethod
    def normalize_slippage(cls, value: Decimal) -> Decimal:
        return canonical_rate(value, "fill.slippage_bps")

    @field_validator("occurred_at")
    @classmethod
    def normalize_occurred_at(cls, value: datetime) -> datetime:
        return canonical_utc(value)


def projection_checksum(
    cash: tuple[CashProjection, ...],
    positions: tuple[PositionProjection, ...],
    reservations: tuple[Reservation, ...],
) -> str:
    return canonical_hash(
        {
            "cash": [item.model_dump(mode="python") for item in cash],
            "positions": [item.model_dump(mode="python") for item in positions],
            "reservations": [item.model_dump(mode="python") for item in reservations],
        }
    )


def _validate_fx(
    native: Money,
    rmb: Money,
    evidence: ExchangeRateEvidence | None,
) -> None:
    if rmb.currency != CNY:
        raise DomainInvariantViolation("converted amount must use CNY")
    if native.currency == CNY:
        if evidence is not None or native.amount != rmb.amount:
            raise DomainInvariantViolation("CNY amount must map 1:1 without FX evidence")
        return
    if evidence is None:
        raise DomainInvariantViolation("cross-currency fact requires FX evidence")
    if evidence.base_currency != native.currency:
        raise DomainInvariantViolation("FX evidence base currency does not match")
    expected = derived_money(
        native.amount * evidence.rate,
        rule_version=SIMULATION_RULE_VERSION,
        label="converted RMB",
    )
    if expected != rmb.amount:
        raise DomainInvariantViolation("RMB amount does not match FX evidence")


def _validate_converted(
    native: Money,
    rmb: Money,
    evidence: ExchangeRateEvidence | None,
) -> None:
    if native.amount == ZERO:
        if rmb.currency != CNY or rmb.amount != ZERO:
            raise DomainInvariantViolation("zero native fact must have zero RMB fact")
        return
    _validate_fx(native, rmb, evidence)


def _require_positive(money: Money, label: str) -> None:
    if money.amount <= ZERO:
        raise DomainInvariantViolation(f"{label} must be positive")


def _require_positive_rmb(money: Money, label: str) -> None:
    _require_positive(money, label)
    if money.currency != CNY:
        raise DomainInvariantViolation(f"{label} must use CNY")


def _require_nonnegative(money: Money, label: str) -> None:
    if money.amount < ZERO:
        raise DomainInvariantViolation(f"{label} cannot be negative")


def _canonical(value: object) -> object:
    if isinstance(value, Decimal):
        if value.is_zero():
            return "0"
        return format(value.normalize(), "f")
    if isinstance(value, datetime):
        utc = canonical_utc(value)
        return utc.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, FrozenModel):
        return _canonical(value.model_dump(mode="python"))
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value
