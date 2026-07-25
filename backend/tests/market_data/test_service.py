from __future__ import annotations

import asyncio
from decimal import Decimal
from math import nan
from pathlib import Path

import pytest

from finance_god.market_data import (
    DQTriggerRequest,
    DQWorkflowReceipt,
    ErrorKind,
    FailClosedPublishedState,
    MarketDataApplication,
    MarketDataError,
    MarketDataService,
    PandaCalendarPublishedState,
    StaticPublishedState,
)
from finance_god.market_data.bar_cache import PersistentBarCache
from finance_god.market_data.contracts import DataFrequency, ReleaseState
from finance_god.market_data.instruments import DEFAULT_INSTRUMENT_MASTER

from .conftest import NOW, FakeSDK, adapter, bar, stock_snapshot


class RecordingWorkflow:
    def __init__(self) -> None:
        self.requests: list[DQTriggerRequest] = []

    async def start(self, request: DQTriggerRequest) -> DQWorkflowReceipt:
        self.requests.append(request)
        return DQWorkflowReceipt(
            workflow_run_id="persisted-dq-run",
            idempotency_key=request.idempotency_key,
        )


def test_service_fails_closed_before_sdk_when_publication_state_is_unknown() -> None:
    sdk = FakeSDK()
    service = MarketDataService(
        adapter=adapter(sdk),
        now=lambda: NOW,
        published_state=FailClosedPublishedState(),
    )
    application = MarketDataApplication(
        service,
        dq_workflow=RecordingWorkflow(),
    )

    batch = asyncio.run(application.quotes(["000001.SZ"]))

    assert batch.quotes == ()
    assert batch.diagnostics[0].code.value == "data_not_released"
    assert sdk.calls == []


def test_service_exposes_research_data_but_never_marks_it_trade_eligible() -> None:
    sdk = FakeSDK()
    sdk.responses["get_stock_rt_min"] = [bar("20260723 10:31:00")]
    sdk.responses["get_stock_rt_daily"] = [stock_snapshot()]
    service = MarketDataService(
        adapter=adapter(sdk),
        now=lambda: NOW,
        published_state=StaticPublishedState(ReleaseState.RELEASED),
    )
    application = MarketDataApplication(
        service,
        dq_workflow=RecordingWorkflow(),
    )

    batch = asyncio.run(application.quotes(["000001.SZ"]))

    assert batch.quotes
    assert batch.trade_eligible is False
    assert batch.quotes[0].trade_eligible is False
    assert (
        batch.quotes[0].instrument_master_identity == DEFAULT_INSTRUMENT_MASTER.identity
    )
    assert (
        batch.quotes[0].instrument_master_version == DEFAULT_INSTRUMENT_MASTER.version
    )
    assert batch.quality["000001.SZ"].trade_eligible is False
    assert batch.quality["000001.SZ"].capability_trade_eligible is False


def test_service_exposes_public_read_only_bar_boundary() -> None:
    sdk = FakeSDK()
    sdk.responses["get_stock_rt_min"] = [bar("20260723 10:31:00")]
    service = MarketDataService(
        adapter=adapter(sdk),
        now=lambda: NOW,
        published_state=StaticPublishedState(ReleaseState.RELEASED),
    )

    result = service.read_bars("000001.SZ", limit=20)

    assert result.bars
    assert result.frequency == "1分钟"
    assert result.quality.trade_eligible is False


def test_service_exposes_full_bounded_daily_series_for_research() -> None:
    sdk = FakeSDK()
    sdk.responses["get_stock_daily"] = [
        bar("20260722", close=10.2),
        bar("20260721", close=10.1),
        bar("20260720", close=10.0),
    ]
    service = MarketDataService(
        adapter=adapter(sdk),
        now=lambda: NOW,
        published_state=StaticPublishedState(ReleaseState.RELEASED),
    )

    result = service.read_historical_daily_bars(
        "000001.SZ",
        start_date="20260622",
        end_date="20260722",
    )

    assert len(result.bars) == 3
    assert [item.close for item in result.bars] == [
        Decimal("10.2"),
        Decimal("10.1"),
        Decimal("10.0"),
    ]
    assert result.frequency == "日频"
    assert sdk.calls[-1][1] == {
        "symbol": "000001.SZ",
        "start_date": "20260622",
        "end_date": "20260722",
    }


def test_public_bars_cache_bounded_window_across_service_instances(
    tmp_path: Path,
) -> None:
    cache = PersistentBarCache(tmp_path / "market-bars.sqlite3")
    first_sdk = FakeSDK()
    first_sdk.responses["get_stock_daily"] = [
        bar("20260722", close=10.2),
        bar("20260721", close=10.1),
        bar("20260720", close=10.0),
    ]
    first = MarketDataService(
        adapter=adapter(first_sdk),
        now=lambda: NOW,
        published_state=StaticPublishedState(ReleaseState.RELEASED),
        bar_cache=cache,
    )

    initial = first.read_bars(
        "000001.SZ",
        frequency_override=DataFrequency.DAILY,
    )

    assert len(initial.bars) == 3
    assert first_sdk.calls[-1][1]["start_date"] == "20260305"

    second_sdk = FakeSDK()
    second = MarketDataService(
        adapter=adapter(second_sdk),
        now=lambda: NOW,
        published_state=StaticPublishedState(ReleaseState.RELEASED),
        bar_cache=PersistentBarCache(tmp_path / "market-bars.sqlite3"),
    )

    cached = second.read_bars(
        "000001.SZ",
        frequency_override=DataFrequency.DAILY,
    )

    assert cached.bars == initial.bars
    assert second_sdk.calls == []


def test_service_exposes_source_stamped_company_disclosure_facts() -> None:
    sdk = FakeSDK()
    sdk.responses["get_fina_reports"] = [
        {
            "symbol": "000001.SZ",
            "date": "20260720",
            "end_quarter": "2026Q2",
            "report_type": "interim",
            "revenue": 123.45,
            "missing_metric": nan,
        }
    ]
    service = MarketDataService(
        adapter=adapter(sdk),
        now=lambda: NOW,
        published_state=StaticPublishedState(ReleaseState.RELEASED),
    )

    result = service.read_information_facts(
        "000001.SZ",
        start_quarter="2026q1",
        end_quarter="2026q2",
    )

    assert result.fact_kind == "company_disclosure"
    assert result.symbol == "000001.SZ"
    assert result.trade_eligible is False
    assert result.facts[0].category.value == "financial"
    assert result.facts[0].source.endpoint == "get_fina_reports"
    assert (
        dict((field.name, field.value) for field in result.facts[0].fields)["revenue"]
        == 123.45
    )
    assert (
        dict((field.name, field.value) for field in result.facts[0].fields)[
            "missing_metric"
        ]
        is None
    )
    call_name, call_arguments = sdk.calls[-1]
    assert call_name == "get_fina_reports"
    assert call_arguments["start_quarter"] == "2026q1"
    assert call_arguments["end_quarter"] == "2026q2"


def test_service_exposes_raw_margin_facts_without_sentiment_inference() -> None:
    sdk = FakeSDK()
    sdk.responses["get_margin"] = [
        {
            "symbol": "000001.SZ",
            "date": "20260722",
            "total_balance": 1000.0,
            "short_balance": 250.0,
        }
    ]
    service = MarketDataService(
        adapter=adapter(sdk),
        now=lambda: NOW,
        published_state=StaticPublishedState(ReleaseState.RELEASED),
    )

    result = service.read_sentiment_facts(
        "000001.SZ",
        start_date="20260701",
        end_date="20260723",
    )

    assert result.fact_kind == "margin_balance"
    assert result.trade_eligible is False
    assert result.facts[0].source.endpoint == "get_margin"
    assert all("sentiment" not in field.name for field in result.facts[0].fields)


def test_stock_fact_services_reject_index_as_unsupported_capability() -> None:
    service = MarketDataService(
        adapter=adapter(FakeSDK()),
        now=lambda: NOW,
        published_state=StaticPublishedState(ReleaseState.RELEASED),
    )

    with pytest.raises(MarketDataError) as information:
        service.read_information_facts(
            "000001.SH",
            start_quarter="2026q1",
            end_quarter="2026q2",
        )
    with pytest.raises(MarketDataError) as sentiment:
        service.read_sentiment_facts(
            "000001.SH",
            start_date="20260701",
            end_date="20260723",
        )

    assert information.value.kind is ErrorKind.CAPABILITY
    assert sentiment.value.kind is ErrorKind.CAPABILITY
    assert information.value.endpoint == "get_fina_reports"
    assert sentiment.value.endpoint == "get_margin"


def test_market_get_reports_conflict_without_creating_a_workflow() -> None:
    sdk = FakeSDK()
    sdk.responses["get_stock_rt_min"] = [
        bar("20260723 10:31:00", symbol="600519.SH"),
    ]
    workflow = RecordingWorkflow()
    service = MarketDataService(
        adapter=adapter(sdk),
        now=lambda: NOW,
        published_state=StaticPublishedState(ReleaseState.RELEASED),
    )
    application = MarketDataApplication(service, dq_workflow=workflow)

    batch = asyncio.run(application.quotes(["000001.SZ"]))

    assert batch.quotes == ()
    assert batch.diagnostics[0].code.value == "conflict"
    assert workflow.requests == []


def test_market_get_never_invokes_the_dq_workflow_port() -> None:
    class FailingWorkflow:
        async def start(self, request: DQTriggerRequest) -> DQWorkflowReceipt:
            del request
            raise RuntimeError("DQ workflow unavailable")

    sdk = FakeSDK()
    service = MarketDataService(
        adapter=adapter(sdk),
        now=lambda: NOW,
        published_state=StaticPublishedState(ReleaseState.RELEASED),
    )
    application = MarketDataApplication(service, dq_workflow=FailingWorkflow())

    batch = asyncio.run(application.quotes(["000001.SZ"]))

    assert batch.quotes == ()
    assert batch.diagnostics[0].code.value == "unexpected_missing"


def _calendar_day(
    nature_date: int,
    *,
    is_trade: int,
    pretrade_date: int,
    next_trade_date: int,
) -> dict[str, object]:
    return {
        "nature_date": nature_date,
        "is_trade": is_trade,
        "exchange": "SH",
        "pretrade_date": pretrade_date,
        "next_trade_date": next_trade_date,
    }


def _range_filtered_trade_cal(sdk: FakeSDK, rows: list[dict[str, object]]) -> None:
    """Serve only calendar rows inside each request window (official SDK shape)."""

    def get_trade_cal(**kwargs: object) -> list[dict[str, object]]:
        sdk.calls.append(("get_trade_cal", kwargs))
        start = str(kwargs["start_date"])
        end = str(kwargs["end_date"])
        return [
            row
            for row in rows
            if start <= str(row["nature_date"]) <= end
        ]

    sdk.get_trade_cal = get_trade_cal  # type: ignore[method-assign]


def test_official_calendar_response_authorizes_released_session() -> None:
    sdk = FakeSDK()
    _range_filtered_trade_cal(
        sdk,
        [
            _calendar_day(
                20260723,
                is_trade=1,
                pretrade_date=20260722,
                next_trade_date=20260724,
            ),
        ],
    )
    sdk.responses["get_stock_rt_min"] = [bar("20260723 10:31:00")]
    sdk.responses["get_stock_rt_daily"] = [stock_snapshot()]
    data_adapter = adapter(sdk)
    service = MarketDataService(
        adapter=data_adapter,
        now=lambda: NOW,
        published_state=PandaCalendarPublishedState(data_adapter),
    )
    application = MarketDataApplication(
        service,
        dq_workflow=RecordingWorkflow(),
    )

    batch = asyncio.run(application.quotes(["000001.SZ"]))
    ready, reason = application.probe_readiness()

    assert batch.quotes
    assert ready is True
    assert reason == "ready"
    calls = [name for name, _ in sdk.calls]
    # quotes: 1 latest_released; readiness: probe + snapshot latest_released + bars latest_released
    assert calls.count("get_trade_cal") == 4
    assert calls.count("get_stock_rt_daily") == 2
    # quotes snapshot + readiness snapshot + readiness bars
    assert calls.count("get_stock_rt_min") == 3


def test_weekend_cold_start_uses_latest_authoritative_open_session() -> None:
    weekend_now = NOW.replace(day=25)
    sdk = FakeSDK()
    _range_filtered_trade_cal(
        sdk,
        [
            _calendar_day(
                20260724,
                is_trade=1,
                pretrade_date=20260723,
                next_trade_date=20260727,
            ),
            _calendar_day(
                20260725,
                is_trade=0,
                pretrade_date=20260724,
                next_trade_date=20260727,
            ),
        ],
    )
    sdk.responses["get_stock_min"] = [bar("20260724 15:00:00")]
    sdk.responses["get_stock_daily"] = [
        stock_snapshot(data_time="20260724", close=10.2)
    ]
    data_adapter = adapter(sdk, now=weekend_now)
    service = MarketDataService(
        adapter=data_adapter,
        now=lambda: weekend_now,
        published_state=PandaCalendarPublishedState(data_adapter),
    )
    application = MarketDataApplication(
        service,
        dq_workflow=RecordingWorkflow(),
    )

    batch = asyncio.run(application.quotes(["000001.SZ"]))

    assert len(batch.quotes) == 1
    quote = batch.quotes[0]
    assert str(quote.last) == "10.2"
    assert quote.provider_time.startswith("2026-07-24T15:00:00")
    assert quote.source_endpoint == "get_stock_min"
    assert quote.market_status == "released"
    assert quote.freshness == "unknown"
    assert quote.session_alignment == "latest_released_session"
    assert quote.previous_close == 10
    assert quote.change_percent == Decimal("0.02")
    assert not any(name == "get_stock_rt_min" for name, _ in sdk.calls)


def test_readiness_probes_quote_and_page_bar_contract_once_per_cache_window() -> None:
    sdk = FakeSDK()
    sdk.responses["get_stock_rt_min"] = [bar("20260723 10:31:00")]
    sdk.responses["get_stock_rt_daily"] = [stock_snapshot()]
    service = MarketDataService(
        adapter=adapter(sdk),
        now=lambda: NOW,
        clock=lambda: 100.0,
        published_state=StaticPublishedState(ReleaseState.RELEASED),
    )

    assert service.probe_readiness() == (True, "ready")
    assert service.probe_readiness() == (True, "ready")

    calls = [name for name, _ in sdk.calls]
    assert calls.count("get_stock_rt_daily") == 1
    # Snapshot + bars each hit the realtime minute endpoint once per probe; the
    # second probe is served from the readiness cache.
    assert calls.count("get_stock_rt_min") == 2


def test_readiness_uses_latest_released_session_on_closed_days() -> None:
    weekend_now = NOW.replace(day=25)
    sdk = FakeSDK()
    _range_filtered_trade_cal(
        sdk,
        [
            _calendar_day(
                20260724,
                is_trade=1,
                pretrade_date=20260723,
                next_trade_date=20260727,
            ),
            _calendar_day(
                20260725,
                is_trade=0,
                pretrade_date=20260724,
                next_trade_date=20260727,
            ),
        ],
    )
    sdk.responses["get_stock_min"] = [bar("20260724 15:00:00")]
    sdk.responses["get_stock_daily"] = [
        stock_snapshot(data_time="20260724", close=10.2)
    ]
    data_adapter = adapter(sdk, now=weekend_now)
    service = MarketDataService(
        adapter=data_adapter,
        now=lambda: weekend_now,
        clock=lambda: 100.0,
        published_state=PandaCalendarPublishedState(data_adapter),
    )

    assert service.probe_readiness() == (True, "ready")
    assert not any(name == "get_stock_rt_min" for name, _ in sdk.calls)
    assert any(name == "get_stock_min" for name, _ in sdk.calls)


def test_readiness_fails_when_page_bar_contract_has_schema_drift() -> None:
    sdk = FakeSDK()
    sdk.responses["get_stock_rt_min"] = [{"symbol": "000001.SZ"}]
    service = MarketDataService(
        adapter=adapter(sdk),
        now=lambda: NOW,
        published_state=StaticPublishedState(ReleaseState.RELEASED),
    )

    assert service.probe_readiness() == (False, "MARKET_DATA_SCHEMA_INVALID")


def test_unsupported_default_bar_symbol_preserves_capability_error() -> None:
    service = MarketDataService(
        adapter=adapter(FakeSDK()),
        now=lambda: NOW,
        published_state=StaticPublishedState(ReleaseState.RELEASED),
    )
    application = MarketDataApplication(
        service,
        dq_workflow=RecordingWorkflow(),
    )

    with pytest.raises(MarketDataError) as captured:
        asyncio.run(application.bars("510300.SH"))

    assert captured.value.kind is ErrorKind.CAPABILITY
    assert captured.value.public_code.value == "MARKET_DATA_CAPABILITY_UNAVAILABLE"


def test_readiness_does_not_depend_on_a_mutating_workflow_port() -> None:
    service = MarketDataService(
        adapter=adapter(FakeSDK()),
        now=lambda: NOW,
        published_state=StaticPublishedState(ReleaseState.RELEASED),
    )

    application = MarketDataApplication(service)

    assert application.probe_readiness() == service.probe_readiness()


def test_quality_failure_without_workflow_port_remains_a_read_result() -> None:
    sdk = FakeSDK()
    sdk.responses["get_stock_rt_min"] = [bar("20260723 10:31:00", symbol="600519.SH")]
    service = MarketDataService(
        adapter=adapter(sdk),
        now=lambda: NOW,
        published_state=StaticPublishedState(ReleaseState.RELEASED),
    )
    application = MarketDataApplication(service, dq_workflow=None)

    batch = asyncio.run(application.quotes(["000001.SZ"]))

    assert batch.quotes == ()
    assert batch.diagnostics[0].code.value == "conflict"


def test_quote_batch_keeps_supported_results_and_reports_unknown_symbols() -> None:
    sdk = FakeSDK()
    sdk.responses["get_stock_rt_min"] = [bar("20260723 10:31:00")]
    sdk.responses["get_stock_rt_daily"] = [stock_snapshot()]
    service = MarketDataService(
        adapter=adapter(sdk),
        now=lambda: NOW,
        published_state=StaticPublishedState(ReleaseState.RELEASED),
    )
    application = MarketDataApplication(
        service,
        dq_workflow=RecordingWorkflow(),
    )

    batch = asyncio.run(application.quotes(["000001.SZ", "999999.SZ"]))

    assert [quote.symbol for quote in batch.quotes] == ["000001.SZ"]
    assert "999999.SZ" in batch.errors
    assert "authoritative master" in batch.errors["999999.SZ"]
