from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from finance_god.trading.access import AuthorizationStatus, AutonomyLevel
from finance_god.trading.mandate import (
    DEFAULT_LIMITS,
    InvestmentMandate,
    default_mandate,
    evaluate_order_authorization,
    market_of,
    order_notional,
)

NOW = datetime(2026, 7, 24, 8, tzinfo=UTC)


def _mandate(**overrides: object) -> InvestmentMandate:
    base = dict(
        mandate_id="mandate-1",
        owner_user_id="owner-1",
        version=1,
        status=AuthorizationStatus.ACTIVE,
        autonomy_level=AutonomyLevel.L0,
        allowed_markets=("CN",),
        allowed_assets=("stock",),
        allowed_sides=("buy",),
        allowed_order_types=("limit",),
        short_markets=(),
        limits=DEFAULT_LIMITS,
        valid_from=NOW,
        valid_until=NOW + timedelta(days=30),
        created_at=NOW,
        created_by="owner-1",
        note=None,
    )
    base.update(overrides)
    return InvestmentMandate(**base)  # type: ignore[arg-type]


def test_default_mandate_is_active_l0_and_lenient() -> None:
    mandate = default_mandate(
        mandate_id="mandate-1", owner_user_id="owner-1", now=NOW, actor="owner-1"
    )
    assert mandate.version == 1
    assert mandate.status is AuthorizationStatus.ACTIVE
    assert mandate.autonomy_level is AutonomyLevel.L0
    assert set(mandate.allowed_markets) == {"CN", "HK", "US"}
    assert set(mandate.allowed_sides) == {"buy", "sell"}
    assert mandate.is_active(NOW)


def test_market_of_infers_from_suffix() -> None:
    assert market_of("600519.SH") == "CN"
    assert market_of("000001.SZ") == "CN"
    assert market_of("430047.BJ") == "CN"
    assert market_of("00700.HK") == "HK"
    assert market_of("AAPL") == "US"


def test_order_notional_paths() -> None:
    assert order_notional(
        order_type="fund", quantity=None, amount=Decimal("500"),
        limit_price=None, reference_price=None,
    ) == Decimal("500")
    assert order_notional(
        order_type="limit", quantity=Decimal("100"), amount=None,
        limit_price=Decimal("10"), reference_price=Decimal("9"),
    ) == Decimal("1000")
    assert order_notional(
        order_type="market", quantity=Decimal("100"), amount=None,
        limit_price=None, reference_price=Decimal("8"),
    ) == Decimal("800")
    assert order_notional(
        order_type="market", quantity=Decimal("100"), amount=None,
        limit_price=None, reference_price=None,
    ) is None


def _evaluate(mandate: InvestmentMandate, **kw: object) -> tuple[str, ...]:
    defaults = dict(
        now=NOW, side="buy", order_type="limit",
        instrument_id="600519.SH", notional=Decimal("1000"),
    )
    defaults.update(kw)
    return tuple(d.code for d in evaluate_order_authorization(mandate, **defaults))  # type: ignore[arg-type]


def test_evaluate_passes_within_scope() -> None:
    assert _evaluate(_mandate()) == ()


def test_evaluate_blocks_inactive_mandate() -> None:
    paused = _mandate(status=AuthorizationStatus.PAUSED)
    assert _evaluate(paused) == ("mandate_inactive",)
    # An active-but-elapsed window also blocks as inactive.
    elapsed = _mandate(valid_until=NOW + timedelta(days=1))
    assert _evaluate(elapsed, now=NOW + timedelta(days=2)) == ("mandate_inactive",)


def test_evaluate_blocks_each_scope_dimension() -> None:
    assert _evaluate(_mandate(), side="sell") == ("side_not_authorized",)
    assert _evaluate(_mandate(), order_type="market") == ("order_type_not_authorized",)
    assert _evaluate(_mandate(), instrument_id="00700.HK") == ("market_not_authorized",)


def test_evaluate_blocks_single_order_limit() -> None:
    tight = _mandate(
        limits=DEFAULT_LIMITS.model_copy(
            update={"max_single_order_amount": Decimal("100")}
        )
    )
    assert _evaluate(tight, notional=Decimal("101")) == ("single_order_limit_exceeded",)
    assert _evaluate(tight, notional=Decimal("100")) == ()
    # A missing notional skips the cap rather than guessing.
    assert _evaluate(tight, notional=None) == ()
