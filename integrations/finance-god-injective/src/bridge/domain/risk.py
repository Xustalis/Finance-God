from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from .models import (
    AccountSnapshot,
    InjectivePlan,
    MarketSnapshot,
    MarketStatus,
    OrderType,
    PlanStatus,
    RiskCheck,
    RiskCode,
    RiskPolicy,
    RiskReport,
    Side,
    TimeInForce,
    _ensure_utc,
    decimal_to_string,
    utc_now,
)

BASIS_POINTS = Decimal("10000")
ZERO = Decimal("0")


def _check(
    code: RiskCode,
    passed: bool,
    message: str,
    *,
    actual: str | None = None,
    limit: str | None = None,
) -> RiskCheck:
    return RiskCheck(
        code=code,
        passed=passed,
        message=message,
        actual=actual,
        limit=limit,
    )


def _is_multiple(value: Decimal, step: Decimal) -> bool:
    return value % step == ZERO


def review_plan(
    plan: InjectivePlan,
    *,
    market: MarketSnapshot,
    account: AccountSnapshot,
    active_order_count: int,
    policy: RiskPolicy,
    reviewed_at: datetime | None = None,
) -> RiskReport:
    """Return every deterministic risk check without changing plan state."""
    if active_order_count < 0:
        raise ValueError("active_order_count cannot be negative")

    checked_at = _ensure_utc(reviewed_at or utc_now())
    notional = plan.price * plan.quantity
    book_valid = (
        market.best_bid > ZERO and market.best_ask > ZERO and market.best_ask >= market.best_bid
    )
    midpoint = (market.best_bid + market.best_ask) / Decimal("2") if book_valid else None
    deviation_bps = (
        abs(plan.price - midpoint) / midpoint * BASIS_POINTS if midpoint is not None else None
    )
    required_balance = notional if plan.side is Side.BUY else plan.quantity
    available_balance = (
        account.quote_available_balance if plan.side is Side.BUY else account.base_available_balance
    )

    market_allowed = (
        plan.market_id == policy.allowed_market_id
        and market.market_id == policy.allowed_market_id
        and plan.ticker == policy.allowed_ticker
        and market.ticker == policy.allowed_ticker
    )
    checks = (
        _check(
            RiskCode.PLAN_STATE,
            plan.status is PlanStatus.DRAFT,
            "plan must be in draft state",
            actual=plan.status.value,
            limit=PlanStatus.DRAFT.value,
        ),
        _check(
            RiskCode.PLAN_NOT_EXPIRED,
            not plan.is_expired(checked_at),
            "plan must be inside its validity window",
            actual=checked_at.isoformat(),
            limit=plan.expires_at.isoformat() if plan.expires_at else None,
        ),
        _check(
            RiskCode.ALLOWED_MARKET,
            market_allowed,
            "plan and quote must match the configured market",
            actual=f"{plan.market_id}:{plan.ticker}|{market.market_id}:{market.ticker}",
            limit=f"{policy.allowed_market_id}:{policy.allowed_ticker}",
        ),
        _check(
            RiskCode.MARKET_ACTIVE,
            market.status is MarketStatus.ACTIVE,
            "market must be active",
            actual=market.status.value,
            limit=MarketStatus.ACTIVE.value,
        ),
        _check(
            RiskCode.SIDE_ALLOWED,
            plan.side in {Side.BUY, Side.SELL},
            "side must be buy or sell",
            actual=plan.side.value,
            limit="buy|sell",
        ),
        _check(
            RiskCode.LIMIT_ORDER,
            plan.order_type is OrderType.LIMIT,
            "only limit orders are allowed",
            actual=plan.order_type.value,
            limit=OrderType.LIMIT.value,
        ),
        _check(
            RiskCode.GTC,
            plan.time_in_force is TimeInForce.GTC,
            "only GTC time in force is allowed",
            actual=plan.time_in_force.value,
            limit=TimeInForce.GTC.value,
        ),
        _check(
            RiskCode.POSITIVE_PRICE,
            plan.price > ZERO,
            "price must be positive",
            actual=decimal_to_string(plan.price),
            limit=">0",
        ),
        _check(
            RiskCode.POSITIVE_QUANTITY,
            plan.quantity > ZERO,
            "quantity must be positive",
            actual=decimal_to_string(plan.quantity),
            limit=">0",
        ),
        _check(
            RiskCode.PRICE_TICK,
            _is_multiple(plan.price, market.min_price_tick_size),
            "price must align to the market tick",
            actual=decimal_to_string(plan.price),
            limit=decimal_to_string(market.min_price_tick_size),
        ),
        _check(
            RiskCode.QUANTITY_STEP,
            _is_multiple(plan.quantity, market.min_quantity_tick_size),
            "quantity must align to the market step",
            actual=decimal_to_string(plan.quantity),
            limit=decimal_to_string(market.min_quantity_tick_size),
        ),
        _check(
            RiskCode.MAX_NOTIONAL,
            notional <= policy.max_notional,
            "notional must not exceed the configured maximum",
            actual=decimal_to_string(notional),
            limit=decimal_to_string(policy.max_notional),
        ),
        _check(
            RiskCode.ORDER_BOOK_VALID,
            book_valid,
            "best bid and ask must form a valid order book",
            actual=(f"{decimal_to_string(market.best_bid)}:{decimal_to_string(market.best_ask)}"),
            limit="0<bid<=ask",
        ),
        _check(
            RiskCode.PRICE_DEVIATION,
            deviation_bps is not None and deviation_bps <= policy.max_price_deviation_bps,
            "price deviation from midpoint must be inside the configured limit",
            actual=(
                decimal_to_string(deviation_bps) if deviation_bps is not None else "unavailable"
            ),
            limit=decimal_to_string(policy.max_price_deviation_bps),
        ),
        _check(
            RiskCode.SUFFICIENT_BALANCE,
            available_balance >= required_balance,
            "available balance must cover the order",
            actual=decimal_to_string(available_balance),
            limit=decimal_to_string(required_balance),
        ),
        _check(
            RiskCode.ACTIVE_ORDER_LIMIT,
            active_order_count < policy.max_active_orders,
            "active order count must remain below the configured maximum",
            actual=str(active_order_count),
            limit=str(policy.max_active_orders),
        ),
    )
    return RiskReport(
        plan_id=plan.id,
        plan_revision=plan.revision,
        market_id=plan.market_id,
        reviewed_at=checked_at,
        notional=notional,
        midpoint=midpoint,
        checks=checks,
    )
