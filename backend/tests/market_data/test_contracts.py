from __future__ import annotations

from datetime import timedelta

import pytest
from finance_god.market_data import (
    AssetClass,
    DataCategory,
    DataEnvelope,
    DataFrequency,
    DiagnosticCode,
    EmptyMeaning,
    FreshnessPolicy,
    FreshnessStatus,
    InstrumentId,
    InstrumentMaster,
    MarketType,
    ReleaseState,
    UnknownInstrumentError,
)
from finance_god.market_data.normalization import PandaDataNormalizer
from pydantic import ValidationError

from .conftest import NOW, bar


def test_instrument_master_resolves_canonical_and_alias_without_guessing() -> None:
    instrument = InstrumentId(
        symbol="ACME.US",
        provider_symbol="ACME",
        market=MarketType.US,
        asset_class=AssetClass.EQUITY,
        currency="USD",
        aliases=("US:ACME",),
    )
    master = InstrumentMaster((instrument,))

    assert master.resolve(" acme.us ") == instrument
    assert master.resolve("us:acme") == instrument
    assert master.resolve("acme") == instrument
    with pytest.raises(UnknownInstrumentError, match="authoritative master"):
        master.resolve("UNKNOWN")


def test_instrument_and_ohlc_contracts_are_frozen_and_strict() -> None:
    instrument = InstrumentId(
        symbol="000001.SZ",
        provider_symbol="000001.SZ",
        market=MarketType.CN,
        asset_class=AssetClass.EQUITY,
        currency="CNY",
    )
    with pytest.raises(ValidationError):
        instrument.symbol = "000002.SZ"

    normalizer = PandaDataNormalizer(FreshnessPolicy())
    invalid = bar("20260723 10:30:00")
    invalid["high"] = 9.0
    envelope = normalizer.bars(
        [invalid],
        instrument=instrument,
        endpoint="get_stock_rt_min",
        frequency=DataFrequency.MINUTE_1,
        ingested_at=NOW,
        release_state=ReleaseState.RELEASED,
        start_date="20260723",
        end_date="20260723",
        limit=10,
    )

    assert envelope.items == ()
    assert envelope.empty_meaning is EmptyMeaning.UNEXPECTED_MISSING
    assert envelope.diagnostics[0].code.value == "schema_drift"


def test_bar_normalizer_rejects_out_of_order_and_duplicate_timestamps() -> None:
    instrument = InstrumentId(
        symbol="000001.SZ",
        provider_symbol="000001.SZ",
        market=MarketType.CN,
        asset_class=AssetClass.EQUITY,
        currency="CNY",
    )
    normalizer = PandaDataNormalizer(FreshnessPolicy())
    ordered = normalizer.bars(
        [bar("20260723 10:31:00"), bar("20260723 10:30:00")],
        instrument=instrument,
        endpoint="get_stock_rt_min",
        frequency=DataFrequency.MINUTE_1,
        ingested_at=NOW,
        release_state=ReleaseState.RELEASED,
        start_date="20260723",
        end_date="20260723",
        limit=10,
    )

    assert ordered.items == ()
    assert "out-of-order" in ordered.diagnostics[0].message

    duplicated = normalizer.bars(
        [bar("20260723 10:30:00"), bar("20260723 10:30:00")],
        instrument=instrument,
        endpoint="get_stock_rt_min",
        frequency=DataFrequency.MINUTE_1,
        ingested_at=NOW,
        release_state=ReleaseState.RELEASED,
        start_date="20260723",
        end_date="20260723",
        limit=10,
    )
    assert duplicated.items == ()
    assert "duplicate" in duplicated.diagnostics[0].message


def test_historical_minute_accepts_declared_provider_descending_order_only() -> None:
    instrument = InstrumentId(
        symbol="000001.SZ",
        provider_symbol="000001.SZ",
        market=MarketType.CN,
        asset_class=AssetClass.EQUITY,
        currency="CNY",
    )
    normalizer = PandaDataNormalizer(FreshnessPolicy())
    descending = normalizer.bars(
        [
            bar("20260723 10:31:00"),
            bar("20260723 10:30:00"),
            bar("20260723 10:29:00"),
        ],
        instrument=instrument,
        endpoint="get_stock_min",
        frequency=DataFrequency.MINUTE_1,
        ingested_at=NOW,
        release_state=ReleaseState.RELEASED,
        start_date="20260723",
        end_date="20260723",
        limit=2,
    )
    mixed = normalizer.bars(
        [
            bar("20260723 10:31:00"),
            bar("20260723 10:29:00"),
            bar("20260723 10:30:00"),
        ],
        instrument=instrument,
        endpoint="get_stock_min",
        frequency=DataFrequency.MINUTE_1,
        ingested_at=NOW,
        release_state=ReleaseState.RELEASED,
        start_date="20260723",
        end_date="20260723",
        limit=2,
    )

    assert [item.source.data_time.minute for item in descending.items] == [31, 30]
    assert mixed.items == ()
    assert "out-of-order" in mixed.diagnostics[0].message


def test_freshness_distinguishes_trade_date_from_release_state() -> None:
    policy = FreshnessPolicy()
    data_time = NOW - timedelta(seconds=1)

    pending = policy.evaluate(
        market=MarketType.CN,
        category=DataCategory.SNAPSHOT,
        frequency=DataFrequency.SNAPSHOT,
        data_time=data_time,
        trading_date="20260723",
        provider_published_at=data_time,
        evaluated_at=NOW,
        release_state=ReleaseState.CLOSED_PENDING,
    )
    released = policy.evaluate(
        market=MarketType.CN,
        category=DataCategory.SNAPSHOT,
        frequency=DataFrequency.SNAPSHOT,
        data_time=data_time,
        trading_date="20260723",
        provider_published_at=data_time,
        evaluated_at=NOW,
        release_state=ReleaseState.RELEASED,
    )

    assert pending.status is FreshnessStatus.NOT_RELEASED
    assert released.status is FreshnessStatus.CURRENT
    assert pending.rule_version == released.rule_version


def test_negative_numbers_and_naive_source_times_are_rejected() -> None:
    invalid = bar("20260723 10:30:00")
    invalid["volume"] = -1
    instrument = InstrumentId(
        symbol="000001.SZ",
        provider_symbol="000001.SZ",
        market=MarketType.CN,
        asset_class=AssetClass.EQUITY,
        currency="CNY",
    )
    result = PandaDataNormalizer(FreshnessPolicy()).bars(
        [invalid],
        instrument=instrument,
        endpoint="get_stock_rt_min",
        frequency=DataFrequency.MINUTE_1,
        ingested_at=NOW,
        release_state=ReleaseState.RELEASED,
        start_date="20260723",
        end_date="20260723",
        limit=10,
    )
    assert result.items == ()
    assert result.diagnostics[0].code.value == "schema_drift"


def test_unexpected_missing_envelope_requires_matching_diagnostic() -> None:
    with pytest.raises(ValueError, match="matching diagnostic"):
        DataEnvelope((), (), EmptyMeaning.UNEXPECTED_MISSING)


@pytest.mark.parametrize(
    ("rows", "start_date", "end_date", "message"),
    [
        ([bar("20260723 10:30:00", symbol="600519.SH")], "20260723", "20260723", "different instrument"),
        ([bar("20260722 10:30:00")], "20260723", "20260723", "outside request range"),
        ([bar("20260723")], "20260723", "20260723", "granularity"),
    ],
)
def test_bar_normalizer_rejects_wrong_symbol_range_and_granularity(
    rows: list[dict[str, object]],
    start_date: str,
    end_date: str,
    message: str,
) -> None:
    instrument = InstrumentId(
        symbol="000001.SZ",
        provider_symbol="000001.SZ",
        market=MarketType.CN,
        asset_class=AssetClass.EQUITY,
        currency="CNY",
    )

    result = PandaDataNormalizer(FreshnessPolicy()).bars(
        rows,
        instrument=instrument,
        endpoint="get_stock_rt_min",
        frequency=DataFrequency.MINUTE_1,
        ingested_at=NOW,
        release_state=ReleaseState.RELEASED,
        start_date=start_date,
        end_date=end_date,
        limit=10,
    )

    assert result.items == ()
    assert message in result.diagnostics[0].message
    assert result.diagnostics[0].code in {
        DiagnosticCode.CONFLICT,
        DiagnosticCode.SCHEMA_DRIFT,
    }
