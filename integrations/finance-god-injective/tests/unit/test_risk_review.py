from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from bridge.domain import (
    AccountSnapshot,
    InjectivePlan,
    MarketSnapshot,
    MarketStatus,
    PlanStatus,
    RiskCode,
    RiskPolicy,
    Side,
    review_plan,
)

NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


def make_plan(**overrides: object) -> InjectivePlan:
    values: dict[str, object] = {
        "market_id": "0xinj-usdt",
        "ticker": "INJ/USDT",
        "side": Side.BUY,
        "price": "10.00",
        "quantity": "2.0",
        "created_at": NOW,
    }
    values.update(overrides)
    return InjectivePlan(**values)


def make_market(**overrides: object) -> MarketSnapshot:
    values: dict[str, object] = {
        "market_id": "0xinj-usdt",
        "ticker": "INJ/USDT",
        "status": MarketStatus.ACTIVE,
        "min_price_tick_size": "0.01",
        "min_quantity_tick_size": "0.1",
        "best_bid": "9.99",
        "best_ask": "10.01",
        "observed_at": NOW,
    }
    values.update(overrides)
    return MarketSnapshot(**values)


def make_account(**overrides: object) -> AccountSnapshot:
    values: dict[str, object] = {
        "subaccount_id": "0xsubaccount",
        "quote_available_balance": "25",
        "base_available_balance": "2",
        "observed_at": NOW,
    }
    values.update(overrides)
    return AccountSnapshot(**values)


def make_policy(**overrides: object) -> RiskPolicy:
    values: dict[str, object] = {"allowed_market_id": "0xinj-usdt"}
    values.update(overrides)
    return RiskPolicy(**values)


def review(
    plan: InjectivePlan,
    *,
    market: MarketSnapshot | None = None,
    account: AccountSnapshot | None = None,
    active_order_count: int = 0,
    policy: RiskPolicy | None = None,
):
    return review_plan(
        plan,
        market=market or make_market(),
        account=account or make_account(),
        active_order_count=active_order_count,
        policy=policy or make_policy(),
        reviewed_at=NOW + timedelta(seconds=1),
    )


def failed_codes(report) -> set[RiskCode]:
    return {check.code for check in report.checks if not check.passed}


def test_review_passes_at_maximum_notional_boundary() -> None:
    report = review(make_plan(quantity="2.5"))

    assert report.passed
    assert report.notional == Decimal("25.000")
    assert report.midpoint == Decimal("10.00")
    assert report.violations == ()
    assert set(report.model_dump(mode="json")) >= {
        "passed",
        "checks",
        "notional",
        "midpoint",
    }


def test_review_aggregates_all_material_failures() -> None:
    plan = make_plan(price="12.345", quantity="3.35")
    report = review(
        plan,
        market=make_market(status=MarketStatus.PAUSED),
        account=make_account(quote_available_balance="5"),
        active_order_count=1,
        policy=make_policy(allowed_market_id="0xother"),
    )

    assert not report.passed
    assert {
        RiskCode.ALLOWED_MARKET,
        RiskCode.MARKET_ACTIVE,
        RiskCode.PRICE_TICK,
        RiskCode.QUANTITY_STEP,
        RiskCode.MAX_NOTIONAL,
        RiskCode.PRICE_DEVIATION,
        RiskCode.SUFFICIENT_BALANCE,
        RiskCode.ACTIVE_ORDER_LIMIT,
    } <= failed_codes(report)


def test_buy_uses_quote_balance_and_sell_uses_base_balance() -> None:
    buy = review(
        make_plan(side=Side.BUY),
        account=make_account(quote_available_balance="19.99", base_available_balance="20"),
    )
    sell = review(
        make_plan(side=Side.SELL),
        account=make_account(quote_available_balance="0", base_available_balance="2"),
    )
    sell_without_base = review(
        make_plan(side=Side.SELL),
        account=make_account(quote_available_balance="25", base_available_balance="1.99"),
    )

    assert RiskCode.SUFFICIENT_BALANCE in failed_codes(buy)
    assert sell.passed
    assert RiskCode.SUFFICIENT_BALANCE in failed_codes(sell_without_base)


def test_invalid_order_book_fails_without_fabricating_midpoint() -> None:
    report = review(make_plan(), market=make_market(best_bid="10.01", best_ask="9.99"))

    assert report.midpoint is None
    assert {
        RiskCode.ORDER_BOOK_VALID,
        RiskCode.PRICE_DEVIATION,
    } <= failed_codes(report)


def test_expired_plan_fails_review_and_applies_expired_terminal_state() -> None:
    plan = make_plan(created_at=NOW - timedelta(seconds=300))
    report = review(plan)
    expired = plan.apply_review(report)

    assert RiskCode.PLAN_NOT_EXPIRED in failed_codes(report)
    assert expired.status is PlanStatus.EXPIRED


def test_review_requires_zero_existing_active_orders_by_default() -> None:
    allowed = review(make_plan(), active_order_count=0)
    blocked = review(make_plan(), active_order_count=1)

    assert allowed.passed
    assert RiskCode.ACTIVE_ORDER_LIMIT in failed_codes(blocked)


def test_risk_report_serializes_every_decimal_as_string() -> None:
    payload = review(make_plan()).model_dump(mode="json")

    assert payload["notional"] == "20.000"
    assert payload["midpoint"] == "10.00"
