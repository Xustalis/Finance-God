from __future__ import annotations


import pytest
from finance_god.market_data import (
    DataCategory,
    DataEnvelope,
    DataFrequency,
    EmptyMeaning,
    Freshness,
    FreshnessStatus,
    MarketDataResponseError,
    MarketType,
    NormalizedCalendarDay,
    PandaCalendarPublishedState,
    ReleaseState,
    SourceStamp,
)
from finance_god.market_data.instruments import DEFAULT_INSTRUMENT_MASTER
from finance_god.market_data.normalization import diagnostic
from finance_god.market_data.contracts import (
    DiagnosticCode,
    DiagnosticSeverity,
)

from .conftest import NOW


class CalendarStub:
    def __init__(self, envelope: DataEnvelope[NormalizedCalendarDay]) -> None:
        self.envelope = envelope

    def fetch_calendar(
        self,
        *,
        market: MarketType,
        start_date: str,
        end_date: str,
    ) -> DataEnvelope[NormalizedCalendarDay]:
        del market, start_date, end_date
        return self.envelope


def calendar_day() -> NormalizedCalendarDay:
    source = SourceStamp(
        endpoint="get_trade_cal",
        instrument_master_identity=DEFAULT_INSTRUMENT_MASTER.identity,
        instrument_master_version=DEFAULT_INSTRUMENT_MASTER.version,
        data_time=NOW,
        trading_date="20260723",
        provider_published_at=NOW,
        ingested_at=NOW,
        frequency=DataFrequency.DAILY,
        capability_version="test",
        verification="verified_once_research",
        evidence_ref="test-calendar",
    )
    freshness = Freshness(
        status=FreshnessStatus.CURRENT,
        evaluated_at=NOW,
        data_time=NOW,
        trading_date="20260723",
        provider_published_at=NOW,
        threshold_seconds=86_400,
        age_seconds=0,
        release_state=ReleaseState.RELEASED,
        rule_version="test",
        workflow_key="market_context",
        reason="current authoritative calendar",
    )
    return NormalizedCalendarDay(
        market=MarketType.CN,
        trade_date="20260723",
        is_open=True,
        source=source,
        freshness=freshness,
    )


def evaluate(
    envelope: DataEnvelope[NormalizedCalendarDay],
) -> ReleaseState:
    return (
        PandaCalendarPublishedState(CalendarStub(envelope))
        .evaluate(
            instrument=DEFAULT_INSTRUMENT_MASTER.resolve("000001.SZ"),
            category=DataCategory.SNAPSHOT,
            frequency=DataFrequency.SNAPSHOT,
            trading_date="20260723",
            observed_at=NOW,
        )
        .state
    )


@pytest.mark.parametrize(
    "item",
    [
        calendar_day().model_copy(update={"market": MarketType.HK}),
        calendar_day().model_copy(update={"trade_date": "20260722"}),
        calendar_day().model_copy(
            update={
                "source": calendar_day().source.model_copy(
                    update={"endpoint": "get_stock_daily"}
                )
            }
        ),
        calendar_day().model_copy(
            update={
                "source": calendar_day().source.model_copy(
                    update={"instrument_master_version": "0" * 64}
                )
            }
        ),
    ],
)
def test_calendar_identity_source_and_master_mismatches_fail_closed(
    item: NormalizedCalendarDay,
) -> None:
    with pytest.raises(MarketDataResponseError):
        evaluate(DataEnvelope((item,), (), EmptyMeaning.NOT_EMPTY))


def test_calendar_diagnostics_fail_closed() -> None:
    issue = diagnostic(
        code=DiagnosticCode.SCHEMA_DRIFT,
        scope="CN:20260723",
        message="calendar conflict",
        endpoint="get_trade_cal",
        severity=DiagnosticSeverity.ERROR,
    )

    with pytest.raises(MarketDataResponseError):
        evaluate(
            DataEnvelope(
                (calendar_day(),),
                (issue,),
                EmptyMeaning.NOT_EMPTY,
            )
        )


def test_unknown_freshness_never_becomes_released() -> None:
    item = calendar_day()
    unknown = item.model_copy(
        update={
            "freshness": item.freshness.model_copy(
                update={"status": FreshnessStatus.UNKNOWN}
            )
        }
    )

    assert (
        evaluate(DataEnvelope((unknown,), (), EmptyMeaning.NOT_EMPTY))
        is ReleaseState.UNKNOWN
    )
