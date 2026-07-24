from __future__ import annotations

import asyncio

from finance_god.market_data import (
    DQTriggerRequest,
    DQWorkflowReceipt,
    FailClosedPublishedState,
    MarketDataApplication,
    MarketDataConfigurationError,
    MarketDataService,
    PandaCalendarPublishedState,
    StaticPublishedState,
)
from finance_god.market_data.contracts import ReleaseState
from finance_god.market_data.instruments import DEFAULT_INSTRUMENT_MASTER

from .conftest import NOW, FakeSDK, adapter, stock_snapshot


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


def test_service_creates_audited_data_quality_review_for_conflict() -> None:
    sdk = FakeSDK()
    sdk.responses["get_stock_rt_daily"] = [
        stock_snapshot("600519.SH"),
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
    assert calls.count("get_trade_cal") == 2
    assert calls.count("get_stock_rt_daily") == 1


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
    sdk.responses["get_stock_rt_daily"] = [stock_snapshot("600519.SH")]
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
