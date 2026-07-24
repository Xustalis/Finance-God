from __future__ import annotations

import pytest
from finance_god.market_data import (
    AssetClass,
    DataFrequency,
    DiagnosticCode,
    ErrorKind,
    FactorQuery,
    InstrumentId,
    MarketDataError,
    ReleaseState,
    MarketType,
)
from finance_god.market_data.instruments import DEFAULT_INSTRUMENT_MASTER

from .conftest import US_NOW, FakeSDK, adapter, bar, stock_snapshot


def test_a_share_snapshot_daily_and_1m_use_verified_endpoints() -> None:
    sdk = FakeSDK()
    sdk.responses["get_stock_rt_daily"] = [stock_snapshot()]
    sdk.responses["get_stock_daily"] = [bar("20260723")]
    sdk.responses["get_stock_rt_min"] = [
        bar("20260723 10:30:00"),
        bar("20260723 10:31:00"),
    ]
    subject = adapter(sdk)
    instrument = DEFAULT_INSTRUMENT_MASTER.resolve("000001.SZ")

    snapshot = subject.fetch_snapshot(
        instrument,
        release_state=ReleaseState.RELEASED,
        expected_date="20260723",
    )
    daily = subject.fetch_bars(
        instrument,
        frequency=DataFrequency.DAILY,
        start_date="20260723",
        end_date="20260723",
        limit=20,
        release_state=ReleaseState.RELEASED,
    )
    minute = subject.fetch_bars(
        instrument,
        frequency=DataFrequency.MINUTE_1,
        start_date="20260723",
        end_date="20260723",
        limit=20,
        release_state=ReleaseState.RELEASED,
    )

    assert snapshot.items[0].source.endpoint == "get_stock_rt_daily"
    assert daily.items[0].source.endpoint == "get_stock_daily"
    assert minute.items[-1].source.frequency is DataFrequency.MINUTE_1
    called = [name for name, _ in sdk.calls]
    assert called.count("init_token") == 1
    assert "get_stock_rt_daily" in called
    assert "get_stock_daily" in called
    assert "get_stock_rt_min" in called


@pytest.mark.parametrize("symbol", ["510300.SH", "161725.SZ", "000001.OF"])
def test_fund_etf_lof_are_capability_disabled_without_any_sdk_data_call(
    symbol: str,
) -> None:
    sdk = FakeSDK()
    subject = adapter(sdk, now=US_NOW)
    instrument = DEFAULT_INSTRUMENT_MASTER.resolve(symbol)

    result = subject.fetch_bars(
        instrument,
        frequency=DataFrequency.DAILY,
        start_date="20260722",
        end_date="20260723",
        limit=10,
        release_state=ReleaseState.RELEASED,
    )

    assert result.items == ()
    assert result.diagnostics[0].code is DiagnosticCode.CAPABILITY_DISABLED
    assert [name for name, _ in sdk.calls] == []
    assert not any(name.startswith("get_fund_") for name, _ in sdk.calls)
    assert not any(name.startswith("get_stock_") for name, _ in sdk.calls)


def test_us_daily_does_not_fallback_to_previous_day_when_expected_day_is_empty() -> None:
    sdk = FakeSDK()
    sdk.responses["get_us_daily"] = [
        bar("20260722", symbol="AAPL", close=195.0)
    ]
    subject = adapter(sdk, now=US_NOW)
    instrument = DEFAULT_INSTRUMENT_MASTER.resolve("AAPL")

    result = subject.fetch_bars(
        instrument,
        frequency=DataFrequency.DAILY,
        start_date="20260723",
        end_date="20260723",
        limit=10,
        release_state=ReleaseState.RELEASED,
    )

    assert result.items == ()
    assert result.empty_meaning.value == "unexpected_missing"
    calls = [params for name, params in sdk.calls if name == "get_us_daily"]
    assert calls == [
        {"symbol": "AAPL", "start_date": "20260723", "end_date": "20260723"}
    ]


def test_us_daily_does_not_call_upstream_before_release() -> None:
    sdk = FakeSDK()
    subject = adapter(sdk, now=US_NOW)

    result = subject.fetch_bars(
        DEFAULT_INSTRUMENT_MASTER.resolve("AAPL"),
        frequency=DataFrequency.DAILY,
        start_date="20260723",
        end_date="20260723",
        limit=10,
        release_state=ReleaseState.CLOSED_PENDING,
    )

    assert result.items == ()
    assert result.diagnostics[0].code is DiagnosticCode.DATA_NOT_RELEASED
    assert sdk.calls == []


def test_hk_and_us_daily_are_normalized_with_actual_frequency_and_source() -> None:
    sdk = FakeSDK()
    sdk.responses["get_hk_daily"] = [
        bar("20260723", symbol="00700.HK", close=10.2)
    ]
    sdk.responses["get_us_daily"] = [bar("20260723", symbol="AAPL", close=10.2)]
    subject = adapter(sdk, now=US_NOW)

    hk = subject.fetch_bars(
        DEFAULT_INSTRUMENT_MASTER.resolve("700.HK"),
        frequency=DataFrequency.DAILY,
        start_date="20260723",
        end_date="20260723",
        limit=10,
        release_state=ReleaseState.RELEASED,
    )
    us = subject.fetch_bars(
        DEFAULT_INSTRUMENT_MASTER.resolve("AAPL.US"),
        frequency=DataFrequency.DAILY,
        start_date="20260723",
        end_date="20260723",
        limit=10,
        release_state=ReleaseState.RELEASED,
    )

    assert hk.items[0].source.endpoint == "get_hk_daily"
    assert us.items[0].source.endpoint == "get_us_daily"
    assert all(item.source.frequency is DataFrequency.DAILY for item in (*hk.items, *us.items))


def test_empty_missing_columns_and_invalid_ohlc_are_explicit_diagnostics() -> None:
    sdk = FakeSDK()
    subject = adapter(sdk)
    instrument = DEFAULT_INSTRUMENT_MASTER.resolve("000001.SZ")

    empty = subject.fetch_snapshot(
        instrument, release_state=ReleaseState.RELEASED
    )
    sdk.responses["get_stock_rt_daily"] = [{"symbol": "000001.SZ"}]
    missing = subject.fetch_snapshot(
        instrument, release_state=ReleaseState.RELEASED
    )
    sdk.responses["get_stock_rt_daily"] = [
        {**stock_snapshot(), "high": 1.0}
    ]
    invalid = subject.fetch_snapshot(
        instrument, release_state=ReleaseState.RELEASED
    )

    assert empty.diagnostics[0].code is DiagnosticCode.UNEXPECTED_MISSING
    assert missing.diagnostics[0].code is DiagnosticCode.SCHEMA_DRIFT
    assert invalid.diagnostics[0].code is DiagnosticCode.SCHEMA_DRIFT


def test_snapshot_rejects_any_wrong_symbol_without_selecting_a_matching_row() -> None:
    sdk = FakeSDK()
    sdk.responses["get_stock_rt_daily"] = [
        stock_snapshot("000001.SZ"),
        stock_snapshot("600519.SH"),
    ]
    subject = adapter(sdk)

    result = subject.fetch_snapshot(
        DEFAULT_INSTRUMENT_MASTER.resolve("000001.SZ"),
        release_state=ReleaseState.RELEASED,
        expected_date="20260723",
    )

    assert result.items == ()
    assert result.diagnostics[0].code is DiagnosticCode.CONFLICT
    assert "different instrument" in result.diagnostics[0].message


def test_master_and_calendar_normalizers_validate_schema() -> None:
    sdk = FakeSDK()
    sdk.responses["get_stock_detail"] = [
        {"symbol": "000001.SZ", "name": "平安银行"}
    ]
    sdk.responses["get_trade_cal"] = [
        {"trade_date": "20260722", "is_trading_day": 1},
        {"trade_date": "20260723", "is_trading_day": 1},
    ]
    subject = adapter(sdk)

    master = subject.fetch_master(
        [DEFAULT_INSTRUMENT_MASTER.resolve("000001.SZ")]
    )
    calendar = subject.fetch_calendar(
        market=DEFAULT_INSTRUMENT_MASTER.resolve("000001.SZ").market,
        start_date="20260722",
        end_date="20260723",
    )

    assert master.items[0].name == "平安银行"
    assert [item.trade_date for item in calendar.items] == [
        "20260722",
        "20260723",
    ]


def test_research_endpoint_returns_typed_fact_or_explicit_unsupported() -> None:
    sdk = FakeSDK()
    sdk.responses["get_factor"] = [
        {"symbol": "000001.SZ", "date": "20260723", "value": 1.2}
    ]
    subject = adapter(sdk)
    request = FactorQuery.from_master(
        DEFAULT_INSTRUMENT_MASTER,
        symbol="000001.SZ",
        start_date="20260723",
        end_date="20260723",
        factors=("alpha",),
    )

    facts = subject.fetch_factors(request)

    assert facts.items[0].category.value == "factor"
    assert not hasattr(facts.items[0], "last")


@pytest.mark.parametrize("symbol", ["AAPL.US", "510300.SH", "161725.SZ"])
def test_factor_query_rejects_wrong_market_or_asset_before_sdk_call(
    symbol: str,
) -> None:
    sdk = FakeSDK()
    subject = adapter(sdk, now=US_NOW)

    result = subject.fetch_factors(
        FactorQuery.from_master(
            DEFAULT_INSTRUMENT_MASTER,
            symbol=symbol,
            start_date="20260722",
            end_date="20260723",
            factors=("alpha",),
        )
    )

    assert result.items == ()
    assert result.diagnostics[0].code is DiagnosticCode.CAPABILITY_DISABLED
    assert sdk.calls == []


def test_forged_instrument_cannot_relabel_aapl_as_cn_equity() -> None:
    sdk = FakeSDK()
    subject = adapter(sdk, now=US_NOW)
    forged = InstrumentId(
        symbol="AAPL.US",
        provider_symbol="AAPL",
        market=MarketType.CN,
        asset_class=AssetClass.EQUITY,
        currency="CNY",
    )

    with pytest.raises(ValueError, match="authoritative master"):
        subject.fetch_snapshot(
            forged,
            release_state=ReleaseState.RELEASED,
        )

    assert sdk.calls == []


def test_stale_typed_query_master_version_fails_before_sdk_call() -> None:
    sdk = FakeSDK()
    subject = adapter(sdk)
    query = FactorQuery.from_master(
        DEFAULT_INSTRUMENT_MASTER,
        symbol="000001.SZ",
        start_date="20260723",
        end_date="20260723",
        factors=("alpha",),
    ).model_copy(update={"instrument_master_version": "0" * 64})

    with pytest.raises(ValueError, match="identity/version mismatch"):
        subject.fetch_factors(query)

    assert sdk.calls == []


def test_parameters_are_rejected_not_silently_clamped() -> None:
    sdk = FakeSDK()
    subject = adapter(sdk)
    instrument = DEFAULT_INSTRUMENT_MASTER.resolve("000001.SZ")

    with pytest.raises(ValueError, match="limit"):
        subject.fetch_bars(
            instrument,
            frequency=DataFrequency.DAILY,
            start_date="20260723",
            end_date="20260723",
            limit=1001,
            release_state=ReleaseState.RELEASED,
        )
    with pytest.raises(ValueError, match="YYYYMMDD"):
        subject.fetch_bars(
            instrument,
            frequency=DataFrequency.DAILY,
            start_date="2026-07-23",
            end_date="20260723",
            limit=10,
            release_state=ReleaseState.RELEASED,
        )
    assert sdk.calls == []


def test_secrets_and_full_urls_are_redacted_from_errors_and_repr() -> None:
    sdk = FakeSDK()
    username = "very-secret-user"
    password = "very-secret-password"
    sdk.errors["get_stock_rt_daily"] = PermissionError(
        f"{password} denied at https://example.test/private?user={username}"
    )
    subject = adapter(sdk, username=username, password=password)

    with pytest.raises(MarketDataError) as captured:
        subject.fetch_snapshot(
            DEFAULT_INSTRUMENT_MASTER.resolve("000001.SZ"),
            release_state=ReleaseState.RELEASED,
        )

    rendered = repr(subject) + captured.value.internal_message
    assert username not in rendered
    assert password not in rendered
    assert "https://example.test" not in rendered
    assert "[redacted-secret]" in rendered
    assert captured.value.kind is ErrorKind.PERMISSION
    assert set(captured.value.public_payload()) == {"code", "message", "trace_id"}
