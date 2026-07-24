from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from finance_god.application import (
    ConfirmFundCommand,
    CreateAccountCommand,
    FreezeCashCommand,
    RecordBuyFillCommand,
    RecordCoverFillCommand,
    RecordSellFillCommand,
    RecordShortFillCommand,
    ReservePositionCommand,
)
from finance_god.domain import (
    ExchangeRateEvidence,
    Money,
    ReservationKind,
    VersionReference,
)

NOW_OFFSET = datetime(
    2026, 7, 24, 16, 30, 45, 123456, tzinfo=timezone(timedelta(hours=8))
)
NOW_UTC = datetime(2026, 7, 24, 8, 30, 45, 123456, tzinfo=timezone.utc)
SOURCE = VersionReference(
    object_type="trade_command", object_id="request-1", version="1"
)
MARKET = VersionReference(
    object_type="market_snapshot", object_id="600519.SSE", version="42"
)
FX = ExchangeRateEvidence(
    base_currency="USD",
    quote_currency="CNY",
    rate=Decimal("7.180000000000"),
    observed_at=NOW_OFFSET,
    source=VersionReference(
        object_type="fx_snapshot", object_id="USD/CNY", version="12"
    ),
)


class FixedClock:
    def now(self) -> datetime:
        return NOW_OFFSET


class SequentialIds:
    def __init__(self, *, fixed_message: bool = False) -> None:
        self._value = 0
        self._fixed_message = fixed_message

    def new_id(self, prefix: str) -> str:
        if prefix == "message" and self._fixed_message:
            return "message-fixed"
        self._value += 1
        return f"{prefix}-{self._value}"


class Rules:
    simulation_rule_version = "simulation-rules-v1"


def create_command(
    *,
    key: str = "create-1",
    initial_cash: Decimal = Decimal("100000"),
) -> CreateAccountCommand:
    return CreateAccountCommand(
        owner_user_id="owner-1",
        idempotency_key=key,
        correlation_id=f"correlation-{key}",
        causation_id=f"request-{key}",
        source=SOURCE,
        initial_cash_rmb=initial_cash,
    )


def freeze_command(
    account_id: str,
    amount: Decimal,
    *,
    key: str,
    order: str,
    instrument: str | None = None,
    currency: str = "CNY",
    reservation_kind: ReservationKind = ReservationKind.CASH_BUY,
    exchange_rate: ExchangeRateEvidence | None = None,
) -> FreezeCashCommand:
    bound_instrument = instrument or (
        "FUND.OF"
        if reservation_kind is ReservationKind.FUND_SUBSCRIPTION
        else "600519.SSE"
    )
    return FreezeCashCommand(
        owner_user_id="owner-1",
        idempotency_key=key,
        correlation_id=f"correlation-{key}",
        causation_id=f"request-{key}",
        source=SOURCE,
        account_id=account_id,
        order_id=order,
        instrument_id=bound_instrument,
        amount=Money(currency=currency, amount=amount),
        reservation_kind=reservation_kind,
        exchange_rate_evidence=(
            exchange_rate
            if exchange_rate is not None
            else (FX if currency == "USD" else None)
        ),
    )


def buy_command(
    account_id: str,
    reservation_id: str,
    *,
    key: str,
    order: str,
    instrument: str = "600519.SSE",
    quantity: Decimal = Decimal("1"),
    price: Decimal = Decimal("100"),
    fee: Decimal = Decimal("0"),
    currency: str = "CNY",
    exchange_rate: ExchangeRateEvidence | None = None,
) -> RecordBuyFillCommand:
    return RecordBuyFillCommand(
        owner_user_id="owner-1",
        idempotency_key=key,
        correlation_id=f"correlation-{key}",
        causation_id=f"request-{key}",
        source=SOURCE,
        account_id=account_id,
        reservation_id=reservation_id,
        order_id=order,
        instrument_id=instrument,
        quantity=quantity,
        price=price,
        fee=fee,
        currency=currency,
        slippage_bps=Decimal("2.5"),
        market_evidence=MARKET,
        model_version="fill-model-v1",
        exchange_rate_evidence=(
            exchange_rate
            if exchange_rate is not None
            else (FX if currency == "USD" else None)
        ),
    )


def sell_command(
    account_id: str,
    *,
    key: str,
    order: str,
    instrument: str = "600519.SSE",
    quantity: Decimal = Decimal("1"),
    price: Decimal = Decimal("110"),
    fee: Decimal = Decimal("1"),
    currency: str = "CNY",
) -> RecordSellFillCommand:
    return RecordSellFillCommand(
        owner_user_id="owner-1",
        idempotency_key=key,
        correlation_id=f"correlation-{key}",
        causation_id=f"request-{key}",
        source=SOURCE,
        account_id=account_id,
        order_id=order,
        instrument_id=instrument,
        quantity=quantity,
        price=price,
        fee=fee,
        currency=currency,
        slippage_bps=Decimal("1"),
        market_evidence=MARKET,
        model_version="fill-model-v1",
        exchange_rate_evidence=FX if currency == "USD" else None,
    )


def short_command(
    account_id: str, reservation_id: str, *, key: str, order: str
) -> RecordShortFillCommand:
    return RecordShortFillCommand(
        owner_user_id="owner-1",
        idempotency_key=key,
        correlation_id=f"correlation-{key}",
        causation_id=f"request-{key}",
        source=SOURCE,
        account_id=account_id,
        reservation_id=reservation_id,
        order_id=order,
        instrument_id="600519.SSE",
        quantity=Decimal("1"),
        price=Decimal("100"),
        fee=Decimal("0"),
        borrow_fee=Decimal("1"),
        currency="CNY",
        slippage_bps=Decimal("1"),
        market_evidence=MARKET,
        model_version="fill-model-v1",
        margin_change_rmb=Decimal("50"),
    )


def cover_command(
    account_id: str, reservation_id: str, *, key: str, order: str
) -> RecordCoverFillCommand:
    return RecordCoverFillCommand(
        owner_user_id="owner-1",
        idempotency_key=key,
        correlation_id=f"correlation-{key}",
        causation_id=f"request-{key}",
        source=SOURCE,
        account_id=account_id,
        reservation_id=reservation_id,
        order_id=order,
        instrument_id="600519.SSE",
        quantity=Decimal("1"),
        price=Decimal("100"),
        fee=Decimal("1"),
        currency="CNY",
        slippage_bps=Decimal("1"),
        market_evidence=MARKET,
        model_version="fill-model-v1",
    )


def fund_command(
    account_id: str,
    reservation_id: str,
    *,
    key: str,
    order: str,
    units: Decimal,
    nav: Decimal,
    fee: Decimal,
) -> ConfirmFundCommand:
    return ConfirmFundCommand(
        owner_user_id="owner-1",
        idempotency_key=key,
        correlation_id=f"correlation-{key}",
        causation_id=f"request-{key}",
        source=SOURCE,
        account_id=account_id,
        reservation_id=reservation_id,
        order_id=order,
        instrument_id="FUND.OF",
        units=units,
        nav=nav,
        fee=fee,
        currency="CNY",
        market_evidence=MARKET,
        model_version="fund-model-v1",
        settled=True,
    )


def reserve_fund_position(
    account_id: str, *, key: str, order: str, quantity: Decimal
) -> ReservePositionCommand:
    return ReservePositionCommand(
        owner_user_id="owner-1",
        idempotency_key=key,
        correlation_id=f"correlation-{key}",
        causation_id=f"request-{key}",
        source=SOURCE,
        account_id=account_id,
        order_id=order,
        instrument_id="FUND.OF",
        quantity=quantity,
    )
