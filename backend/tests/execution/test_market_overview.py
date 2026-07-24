from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from finance_god.application.market_overview import (
    MARKET_OVERVIEW_ALGORITHM_VERSION,
    build_market_overview,
)
from finance_god.market_data.service import MarketQuote, QuoteBatch

NOW = datetime(2026, 7, 24, 2, 31, tzinfo=UTC)


def _quote(
    symbol: str,
    change_percent: str | None,
    *,
    volume: str = "1000",
    freshness: str = "current",
) -> MarketQuote:
    change = (
        Decimal(change_percent) * Decimal("10")
        if change_percent is not None
        else None
    )
    provider_minute = {
        "000001.SZ": "31",
        "000002.SZ": "32",
        "600519.SH": "33",
    }.get(symbol, "30")
    return MarketQuote(
        symbol=symbol,
        name=symbol,
        asset_type="equity",
        market="CN",
        currency="CNY",
        last=Decimal("10") + (change or Decimal(0)),
        open=Decimal("10"),
        high=Decimal("11"),
        low=Decimal("9"),
        previous_close=Decimal("10"),
        change=change,
        change_percent=(
            Decimal(change_percent) if change_percent is not None else None
        ),
        volume=Decimal(volume),
        amount=Decimal("10000"),
        provider_time=f"2026-07-24T10:{provider_minute}:00+08:00",
        retrieved_at=NOW,
        frequency="realtime",
        freshness=freshness,
        market_status="in_session",
        source_endpoint="get_stock_rt_daily",
        capability_version="capability-v1",
        instrument_master_identity="cn-equity",
        instrument_master_version="master-v1",
    )


def test_market_overview_returns_versioned_defined_backend_indicators() -> None:
    batch = QuoteBatch(
        requested_at=NOW,
        cache_hit=False,
        quotes=(
            _quote("000001.SZ", "0.01"),
            _quote("000002.SZ", "0.02", volume="3000"),
            _quote("600519.SH", "-0.01"),
        ),
        errors={},
    )

    result = build_market_overview(batch)
    indicators = {item.code: item for item in result.data.indicators}

    assert result.algorithm_version == MARKET_OVERVIEW_ALGORITHM_VERSION
    assert result.version.startswith("market-overview:")
    assert result.data.signal.tendency == "positive"
    assert result.data.signal.consistency_percent == Decimal("66.67")
    assert "不代表全市场或交易建议" in result.data.signal.definition
    assert indicators["advance_ratio"].value == Decimal("66.67")
    assert indicators["average_change"].value == Decimal("0.67")
    assert indicators["change_dispersion"].value == Decimal("1.25")
    assert indicators["fresh_coverage"].value == Decimal("100.00")
    assert all(indicator.definition for indicator in result.data.indicators)
    assert result.data_status.provider_time == "2026-07-24T10:33:00+08:00"
    assert result.data_status.frequency == "realtime"
    assert result.data_status.freshness == "fresh"


def test_market_overview_exposes_missing_input_without_default_scores() -> None:
    batch = QuoteBatch(
        requested_at=NOW,
        cache_hit=False,
        quotes=(_quote("000001.SZ", None, freshness="stale"),),
        errors={"000002.SZ": "PROVIDER_TIMEOUT"},
    )

    result = build_market_overview(batch)
    indicators = {item.code: item for item in result.data.indicators}

    assert result.data.signal.tendency == "unavailable"
    assert result.data.signal.consistency_percent is None
    assert indicators["advance_ratio"].value is None
    assert indicators["change_dispersion"].value is None
    assert indicators["average_change"].value is None
    assert result.data_status.freshness == "stale"
    assert {warning.code for warning in result.warnings} == {
        "PARTIAL_QUOTE_FAILURE",
        "CHANGE_PERCENT_UNAVAILABLE",
    }


def test_market_overview_version_changes_with_input_or_algorithm_identity() -> None:
    first = build_market_overview(
        QuoteBatch(
            requested_at=NOW,
            cache_hit=False,
            quotes=(_quote("000001.SZ", "0.01"),),
            errors={},
        )
    )
    second = build_market_overview(
        QuoteBatch(
            requested_at=NOW,
            cache_hit=False,
            quotes=(_quote("000001.SZ", "0.02"),),
            errors={},
        )
    )

    assert first.version != second.version
