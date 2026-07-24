from __future__ import annotations

import asyncio
from math import nan

import pytest

from finance_god.market_data import (
    DQTriggerRequest,
    DQWorkflowReceipt,
    ErrorKind,
    FailClosedPublishedState,
    MarketDataApplication,
    MarketDataConfigurationError,
    MarketDataError,
    MarketDataService,
    PandaCalendarPublishedState,
    StaticPublishedState,
)
from finance_god.market_data.contracts import ReleaseState
from finance_god.market_data.instruments import DEFAULT_INSTRUMENT_MASTER

from .conftest import NOW, FakeSDK, adapter, bar


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


def test_service_creates_audited_data_quality_review_for_conflict() -> None:
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
    assert len(workflow.requests) == 1
    assert workflow.requests[0].workflow_key == "data_quality_review"
    assert workflow.requests[0].recursive_trigger_allowed is False


def test_service_surfaces_dq_workflow_start_failure() -> None:
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

    try:
        asyncio.run(application.quotes(["000001.SZ"]))
    except RuntimeError as error:
        assert "DQ workflow unavailable" in str(error)
    else:
        raise AssertionError("DQ workflow failure must surface explicitly")


def test_official_calendar_response_authorizes_released_session() -> None:
    sdk = FakeSDK()
    sdk.responses["get_trade_cal"] = [
        {
            "nature_date": 20260723,
            "is_trade": 1,
            "exchange": "SH",
            "pretrade_date": 20260722,
            "next_trade_date": 20260724,
        },
    ]
    sdk.responses["get_stock_rt_min"] = [bar("20260723 10:31:00")]
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
    assert calls.count("get_trade_cal") == 2
    assert calls.count("get_stock_rt_daily") == 0
    assert calls.count("get_stock_rt_min") == 3


def test_readiness_probes_quote_and_page_bar_contract_once_per_cache_window() -> None:
    sdk = FakeSDK()
    sdk.responses["get_stock_rt_min"] = [bar("20260723 10:31:00")]
    service = MarketDataService(
        adapter=adapter(sdk),
        now=lambda: NOW,
        clock=lambda: 100.0,
        published_state=StaticPublishedState(ReleaseState.RELEASED),
    )

    assert service.probe_readiness() == (True, "ready")
    assert service.probe_readiness() == (True, "ready")

    calls = [name for name, _ in sdk.calls]
    assert calls.count("get_stock_rt_daily") == 0
    assert calls.count("get_stock_rt_min") == 2


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


def test_readiness_fails_when_workflow_command_port_is_unconfigured() -> None:
    service = MarketDataService(
        adapter=adapter(FakeSDK()),
        now=lambda: NOW,
        published_state=StaticPublishedState(ReleaseState.RELEASED),
    )

    application = MarketDataApplication(service, dq_workflow=None)

    assert application.probe_readiness() == (
        False,
        "DQ_WORKFLOW_COMMAND_PORT_UNCONFIGURED",
    )


def test_quality_failure_without_workflow_port_fails_explicitly() -> None:
    sdk = FakeSDK()
    sdk.responses["get_stock_rt_min"] = [bar("20260723 10:31:00", symbol="600519.SH")]
    service = MarketDataService(
        adapter=adapter(sdk),
        now=lambda: NOW,
        published_state=StaticPublishedState(ReleaseState.RELEASED),
    )
    application = MarketDataApplication(service, dq_workflow=None)

    try:
        asyncio.run(application.quotes(["000001.SZ"]))
    except MarketDataConfigurationError as error:
        assert error.public_code.value == "MARKET_DATA_CONFIGURATION_ERROR"
    else:
        raise AssertionError("missing workflow command port must fail explicitly")


def test_quote_batch_keeps_supported_results_and_reports_unknown_symbols() -> None:
    sdk = FakeSDK()
    sdk.responses["get_stock_rt_min"] = [bar("20260723 10:31:00")]
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
