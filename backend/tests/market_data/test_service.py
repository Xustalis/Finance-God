from __future__ import annotations

from finance_god.market_data import (
    DQTrigger,
    FailClosedPublishedState,
    InMemoryDQTriggerRepository,
    MarketDataService,
    PandaCalendarPublishedState,
    StaticPublishedState,
)
from finance_god.market_data.contracts import ReleaseState
from finance_god.market_data.instruments import DEFAULT_INSTRUMENT_MASTER

from .conftest import NOW, FakeSDK, adapter, stock_snapshot


def test_service_fails_closed_before_sdk_when_publication_state_is_unknown() -> None:
    sdk = FakeSDK()
    service = MarketDataService(
        adapter=adapter(sdk),
        now=lambda: NOW,
        published_state=FailClosedPublishedState(),
    )

    result = service.fetch_snapshot(
        DEFAULT_INSTRUMENT_MASTER.resolve("000001.SZ")
    )

    assert result.items == ()
    assert result.diagnostics[0].code.value == "data_not_released"
    assert sdk.calls == []


def test_service_exposes_research_data_but_never_marks_it_trade_eligible() -> None:
    sdk = FakeSDK()
    sdk.responses["get_stock_rt_daily"] = [stock_snapshot()]
    service = MarketDataService(
        adapter=adapter(sdk),
        now=lambda: NOW,
        published_state=StaticPublishedState(ReleaseState.RELEASED),
    )

    batch = service.fetch_quotes(["000001.SZ"])

    assert batch.quotes
    assert batch.trade_eligible is False
    assert batch.quotes[0].trade_eligible is False
    assert batch.quality["000001.SZ"].trade_eligible is False
    assert batch.quality["000001.SZ"].capability_trade_eligible is False


def test_service_creates_audited_data_quality_review_for_conflict() -> None:
    sdk = FakeSDK()
    sdk.responses["get_stock_rt_daily"] = [
        stock_snapshot("600519.SH"),
    ]
    service = MarketDataService(
        adapter=adapter(sdk),
        now=lambda: NOW,
        published_state=StaticPublishedState(ReleaseState.RELEASED),
    )

    result = service.fetch_snapshot(
        DEFAULT_INSTRUMENT_MASTER.resolve("000001.SZ")
    )
    trigger = service.dq_trigger_for("000001.SZ")
    requests = service.dq_audit_requests()

    assert result.items == ()
    assert result.diagnostics[0].code.value == "conflict"
    assert trigger is not None and trigger.started is True
    assert len(requests) == 1
    assert requests[0].workflow_key == "data_quality_review"
    assert requests[0].recursive_trigger_allowed is False


def test_service_surfaces_dq_workflow_start_failure() -> None:
    class FailingWorkflow:
        def start(self, request):
            del request
            raise RuntimeError("DQ workflow unavailable")

    sdk = FakeSDK()
    service = MarketDataService(
        adapter=adapter(sdk),
        now=lambda: NOW,
        published_state=StaticPublishedState(ReleaseState.RELEASED),
        dq_trigger=DQTrigger(
            InMemoryDQTriggerRepository(),
            FailingWorkflow(),
        ),
    )

    try:
        service.fetch_snapshot(
            DEFAULT_INSTRUMENT_MASTER.resolve("000001.SZ")
        )
    except RuntimeError as error:
        assert "DQ workflow unavailable" in str(error)
    else:
        raise AssertionError("DQ workflow failure must surface explicitly")


def test_calendar_published_state_calls_real_adapter_for_released_session() -> None:
    sdk = FakeSDK()
    sdk.responses["get_trade_cal"] = [
        {"trade_date": "20260723", "is_trading_day": 1},
    ]
    sdk.responses["get_stock_rt_daily"] = [stock_snapshot()]
    data_adapter = adapter(sdk)
    service = MarketDataService(
        adapter=data_adapter,
        now=lambda: NOW,
        published_state=PandaCalendarPublishedState(data_adapter),
    )

    batch = service.fetch_quotes(["000001.SZ"])
    ready, reason = service.probe_readiness()

    assert batch.quotes
    assert ready is True and reason == "ready"
    calls = [name for name, _ in sdk.calls]
    assert calls.count("get_trade_cal") == 2
    assert calls.count("get_stock_rt_daily") == 1
