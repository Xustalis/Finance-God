from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
import server
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from starlette.requests import Request
from starlette.responses import JSONResponse

from finance_god.market_data import (
    CATALOG,
    DQTriggerRequest,
    DQWorkflowReceipt,
    ErrorKind,
    MarketDataApplication,
    MarketDataError,
    MarketDataService,
    PandaCalendarPublishedState,
)
from finance_god.market_data.contracts import DataFrequency
from finance_god.orchestration.workflows import (
    WorkflowCommandRuntime,
    WorkflowCreateCommand,
    WorkflowCreationReceipt,
    WorkflowRun,
    create_workflow_command_runtime_from_environment,
)

from .conftest import NOW, FakeSDK, adapter, bar, stock_snapshot

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def test_workflow_market_context_derives_index_snapshot_from_daily_bars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unsupported_snapshot(symbols: list[str]):
        assert symbols == ["000001.SH"]
        return SimpleNamespace(
            requested_at=NOW,
            cache_hit=False,
            quotes=(),
            errors={"000001.SH": "asset class has no verified snapshot endpoint"},
            diagnostics=(),
            quality={},
        )

    bars = tuple(
        SimpleNamespace(
            open=Decimal("3500"),
            high=Decimal("3560"),
            low=Decimal("3480"),
            close=close,
            volume=Decimal("1000000"),
            amount=Decimal("2000000"),
            provider_time=provider_time,
            freshness="latest_released",
            source_endpoint="get_index_daily",
            capability_version="panda-data-0.0.12",
            instrument_master_identity="000001.SH",
            instrument_master_version="test",
        )
        for close, provider_time in (
            (Decimal("3510"), "2026-07-23T15:00:00+08:00"),
            (Decimal("3530"), "2026-07-24T15:00:00+08:00"),
        )
    )

    class HistoricalApplication:
        async def historical_daily_bars(self, symbol: str, **_: object):
            assert symbol == "000001.SH"
            return SimpleNamespace(frequency="1d", bars=bars)

    monkeypatch.setattr(server, "_candidate_quotes", unsupported_snapshot)
    monkeypatch.setattr(
        server,
        "_services",
        lambda: (SimpleNamespace(), HistoricalApplication()),
    )

    result = asyncio.run(server._workflow_market_context_quotes(["000001.SH"]))

    assert result.errors == {}
    assert len(result.quotes) == 1
    quote = result.quotes[0]
    assert quote.symbol == "000001.SH"
    assert quote.last == Decimal("3530")
    assert quote.previous_close == Decimal("3510")
    assert quote.change == Decimal("20")
    assert quote.source_endpoint == "get_index_daily"
    assert quote.session_alignment == "latest_released_session"


class FailingApplication:
    async def quotes(self, symbols: object) -> object:
        del symbols
        raise MarketDataError(
            ErrorKind.PERMISSION,
            "Bearer secret-token denied at https://private.example.test/data",
            endpoint="get_stock_rt_daily",
        )

    async def bars(self, symbol: str, *, limit: int) -> object:
        del symbol, limit
        raise RuntimeError("password=should-never-reach-browser")

    def probe_readiness(self) -> tuple[bool, str]:
        return False, "MARKET_DATA_DEPENDENCY_UNAVAILABLE"


class StubService:
    def catalog(self) -> tuple[dict[str, object], ...]:
        return tuple(item.model_dump(mode="json") for item in CATALOG.all())


class FactService(StubService):
    def read_information_facts(self, symbol: str, **kwargs: object):
        return SimpleNamespace(
            model_dump=lambda mode="json": {
                "fact_kind": "company_disclosure",
                "symbol": symbol,
                "arguments": kwargs,
            }
        )

    def read_sentiment_facts(self, symbol: str, **kwargs: object):
        return SimpleNamespace(
            model_dump=lambda mode="json": {
                "fact_kind": "margin_balance",
                "symbol": symbol,
                "arguments": kwargs,
            }
        )


class FailingFactService(StubService):
    def read_information_facts(self, symbol: str, **kwargs: object):
        del symbol, kwargs
        raise MarketDataError(ErrorKind.TRANSIENT, "facts unavailable")

    def read_sentiment_facts(self, symbol: str, **kwargs: object):
        del symbol, kwargs
        raise MarketDataError(ErrorKind.TRANSIENT, "facts unavailable")


class UnsupportedFactService(StubService):
    def read_information_facts(self, symbol: str, **kwargs: object):
        del symbol, kwargs
        raise MarketDataError(ErrorKind.CAPABILITY, "facts do not apply")

    def read_sentiment_facts(self, symbol: str, **kwargs: object):
        del symbol, kwargs
        raise MarketDataError(ErrorKind.CAPABILITY, "facts do not apply")


def test_reference_fact_endpoints_return_labeled_non_trading_mock_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        server,
        "_services",
        lambda: (FailingFactService(), FailingApplication()),
    )
    monkeypatch.setattr(
        server.settings,
        "market_reference_mock_fallback",
        True,
    )

    information = asyncio.run(
        server.information_facts(
            _request(
                b"symbol=600519.SH&start_quarter=2026q1&end_quarter=2026q2&limit=3"
            )
        )
    )
    sentiment = asyncio.run(
        server.sentiment_facts(
            _request(b"symbol=600519.SH&start_date=20260701&end_date=20260723")
        )
    )
    information_payload = _payload(information)
    sentiment_payload = _payload(sentiment)

    assert information.status_code == 200
    assert information_payload["data_mode"] == "mock"
    assert information_payload["provider"] == "Finance-God Mock"
    assert information_payload["trade_eligible"] is False
    assert information_payload["fallback_reason"]
    assert information_payload["symbol"] == "600519.SH"
    assert all(
        next(field["value"] for field in fact["fields"] if field["name"] == "source")
        == "Finance-God Mock"
        for fact in information_payload["facts"]
    )

    assert sentiment.status_code == 200
    assert sentiment_payload["data_mode"] == "mock"
    assert sentiment_payload["provider"] == "Finance-God Mock"
    assert sentiment_payload["trade_eligible"] is False
    assert sentiment_payload["fallback_reason"]
    assert sentiment_payload["symbol"] == "600519.SH"


def test_reference_fact_endpoints_do_not_mock_unsupported_instruments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        server,
        "_services",
        lambda: (UnsupportedFactService(), FailingApplication()),
    )
    monkeypatch.setattr(server.settings, "market_reference_mock_fallback", True)

    information = asyncio.run(server.information_facts(_request(b"symbol=000001.SH")))
    sentiment = asyncio.run(server.sentiment_facts(_request(b"symbol=000001.SH")))
    information_payload = _payload(information)
    sentiment_payload = _payload(sentiment)

    assert information.status_code == 422
    assert sentiment.status_code == 422
    assert information_payload["error"]["code"] == "MARKET_DATA_CAPABILITY_UNAVAILABLE"
    assert sentiment_payload["error"]["code"] == "MARKET_DATA_CAPABILITY_UNAVAILABLE"
    assert "data_mode" not in information_payload
    assert "data_mode" not in sentiment_payload


def test_reference_fact_endpoints_keep_explicit_error_when_mock_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        server,
        "_services",
        lambda: (FailingFactService(), FailingApplication()),
    )
    monkeypatch.setattr(
        server.settings,
        "market_reference_mock_fallback",
        False,
    )

    information = asyncio.run(
        server.information_facts(
            _request(b"symbol=600519.SH&start_quarter=2026q1&end_quarter=2026q2")
        )
    )
    sentiment = asyncio.run(server.sentiment_facts(_request(b"symbol=600519.SH")))

    assert information.status_code == 502
    assert sentiment.status_code == 502
    assert _payload(information)["error"]["code"] == "MARKET_DATA_UPSTREAM_TEMPORARY"
    assert _payload(sentiment)["error"]["code"] == "MARKET_DATA_UPSTREAM_TEMPORARY"


def test_daily_bar_route_uses_adapter_supported_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class DailyBarService:
        def read_bars(
            self,
            symbol: str,
            *,
            limit: int,
            frequency_override: DataFrequency | None,
        ) -> object:
            captured.update(
                symbol=symbol,
                limit=limit,
                frequency_override=frequency_override,
            )
            return SimpleNamespace(
                frequency="日频",
                bars=(
                    SimpleNamespace(model_dump=lambda mode="json": {"close": "10.00"}),
                ),
                quality=SimpleNamespace(model_dump=lambda mode="json": {}),
            )

    monkeypatch.setattr(
        server,
        "_services",
        lambda: (DailyBarService(), FailingApplication()),
    )

    response = asyncio.run(server.bars(_request(b"symbol=000001.SZ&frequency=daily")))

    assert response.status_code == 200
    assert captured == {
        "symbol": "000001.SZ",
        "limit": 1_000,
        "frequency_override": DataFrequency.DAILY,
    }


def test_market_api_returns_stable_safe_errors_without_raw_exception_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, "market_data", StubService())
    monkeypatch.setattr(server, "market_application", FailingApplication())
    quotes = asyncio.run(server.quotes(_request(b"symbols=000001.SZ")))
    overview = asyncio.run(server.market_overview(_request(b"symbols=000001.SZ")))
    bars = asyncio.run(server.bars(_request(b"symbol=000001.SZ")))
    invalid = asyncio.run(server.bars(_request(b"symbol=000001.SZ&limit=bad")))
    live = asyncio.run(server.live(_request(b"")))
    ready = asyncio.run(server.ready(_request(b"")))
    health = asyncio.run(server.health(_request(b"")))
    quote_payload = _payload(quotes)
    overview_payload = _payload(overview)
    bars_payload = _payload(bars)
    invalid_payload = _payload(invalid)
    live_payload = _payload(live)
    ready_payload = _payload(ready)
    health_payload = _payload(health)
    rendered = json.dumps(
        [quote_payload, overview_payload, bars_payload, invalid_payload],
        ensure_ascii=False,
    )

    assert quotes.status_code == 502
    assert quote_payload["error"]["code"] == "MARKET_DATA_PERMISSION_DENIED"
    assert overview.status_code == 502
    assert overview_payload["error"]["code"] == "MARKET_DATA_PERMISSION_DENIED"
    assert bars.status_code == 500
    assert bars_payload["error"]["code"] == "MARKET_DATA_INTERNAL_ERROR"
    assert invalid.status_code == 400
    assert invalid_payload["error"]["code"] == "MARKET_DATA_INVALID_REQUEST"
    assert live.status_code == 200
    assert live_payload == {"liveness": "live"}
    assert ready.status_code == 503
    assert ready_payload["readiness"] == "not_ready"
    assert ready_payload["readiness_reason"] == "DQ_WORKFLOW_RUNTIME_UNCONFIGURED"
    assert health.status_code == 503
    assert health_payload["liveness"] == "live"
    assert health_payload["readiness"] == "not_ready"
    assert "secret-token" not in rendered
    assert "private.example.test" not in rendered
    assert "should-never-reach-browser" not in rendered
    assert all(
        len(payload["error"]["trace_id"]) == 32
        for payload in (
            quote_payload,
            overview_payload,
            bars_payload,
            invalid_payload,
        )
    )


def test_overview_api_returns_latest_open_session_during_weekend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RecordingWorkflow:
        async def start(self, request: DQTriggerRequest) -> DQWorkflowReceipt:
            return DQWorkflowReceipt(
                workflow_run_id="weekend-api-regression",
                idempotency_key=request.idempotency_key,
            )

    weekend_now = NOW.replace(day=25)
    sdk = FakeSDK()
    sdk.responses["get_trade_cal"] = [
        {"nature_date": 20260724, "is_trade": 1},
        {"nature_date": 20260725, "is_trade": 0},
    ]
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
    monkeypatch.setattr(server, "market_data", service)
    monkeypatch.setattr(server, "market_application", application)

    response = asyncio.run(server.market_overview(_request(b"symbols=000001.SZ")))
    payload = _payload(response)

    assert response.status_code == 200
    quote = payload["data"]["quotes"][0]
    assert quote["provider_time"].startswith("2026-07-24T15:00:00")
    assert quote["source_endpoint"] == "get_stock_min"
    assert quote["market_status"] == "released"
    assert quote["session_alignment"] == "latest_released_session"
    assert quote["change_percent"] == "0.02"


def test_catalog_api_separates_availability_trade_and_stability_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, "market_data", StubService())
    monkeypatch.setattr(server, "market_application", FailingApplication())

    response = asyncio.run(server.catalog(_request(b"")))
    payload = _payload(response)

    assert response.status_code == 200
    assert payload["summary"]["availability"]["production_available"] == 29
    assert payload["summary"]["trade_eligible"] == 0
    assert payload["summary"]["stability_confirmed"] == 0
    assert payload["summary"]["by_category"]["bar"] == {
        "total": 6,
        "production_available": 6,
        "trade_eligible": 0,
        "stability_confirmed": 0,
    }
    stock_daily = next(
        item for item in payload["datasets"] if item["endpoint"] == "get_stock_daily"
    )
    assert stock_daily["availability"] == "production_available"
    assert stock_daily["trade_eligible"] is False
    assert stock_daily["stability_confirmed"] is False


def test_fact_apis_return_source_facts_and_reject_invalid_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, "market_data", FactService())
    monkeypatch.setattr(server, "market_application", FailingApplication())

    information = asyncio.run(
        server.information_facts(
            _request(b"symbol=000001.SZ&start_quarter=2026q1&end_quarter=2026q2")
        )
    )
    sentiment = asyncio.run(
        server.sentiment_facts(
            _request(b"symbol=000001.SZ&start_date=20260701&end_date=20260723")
        )
    )
    invalid = asyncio.run(
        server.sentiment_facts(_request(b"symbol=000001.SZ&limit=not-a-number"))
    )

    assert information.status_code == 200
    assert _payload(information)["fact_kind"] == "company_disclosure"
    assert _payload(information)["arguments"]["start_quarter"] == "2026q1"
    assert sentiment.status_code == 200
    assert _payload(sentiment)["fact_kind"] == "margin_balance"
    assert _payload(sentiment)["arguments"]["end_date"] == "20260723"
    assert invalid.status_code == 400
    assert _payload(invalid)["error"]["code"] == "MARKET_DATA_INVALID_REQUEST"


def test_dq_adapter_maps_stable_intent_to_public_workflow_command() -> None:
    class CommandSpy:
        def __init__(self) -> None:
            self.commands: list[WorkflowCreateCommand] = []

        async def create(
            self,
            command: WorkflowCreateCommand,
        ) -> WorkflowCreationReceipt:
            self.commands.append(command)
            return cast(
                WorkflowCreationReceipt,
                SimpleNamespace(
                    idempotency_key=command.idempotency_key,
                    run=SimpleNamespace(run_id="persisted-run-1"),
                ),
            )

        async def get(self, run_id: str) -> WorkflowRun | None:
            del run_id
            return None

    request = DQTriggerRequest(
        workflow_key="data_quality_review",
        idempotency_key="a" * 64,
        affected_scope="000001.SZ:1m",
        diagnostic_fingerprints=("b" * 64,),
        requested_at=NOW,
    )
    commands = CommandSpy()
    adapter = server.WorkflowCommandDQAdapter(commands)

    first = asyncio.run(adapter.start(request))
    repeated = asyncio.run(adapter.start(request))

    assert first == repeated
    assert first.workflow_run_id == "persisted-run-1"
    assert len(commands.commands) == 2
    assert commands.commands[0] == commands.commands[1]
    command = commands.commands[0]
    assert command.workflow_key.value == "data_quality_review"
    assert command.idempotency_key == request.idempotency_key
    assert command.input_versions[0].version == request.idempotency_key


def test_dq_adapter_persists_queries_and_idempotently_reuses_real_run(
    tmp_path: Path,
) -> None:
    database = tmp_path / "dq-workflow.db"
    database_url = f"sqlite+aiosqlite:///{database}"
    config = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    alembic_command.upgrade(config, "head")

    async def exercise() -> None:
        runtime = create_workflow_command_runtime_from_environment(
            database_url=database_url
        )
        try:
            adapter = server.WorkflowCommandDQAdapter(runtime)
            request = DQTriggerRequest(
                workflow_key="data_quality_review",
                idempotency_key="c" * 64,
                affected_scope="000001.SZ:1m",
                diagnostic_fingerprints=("d" * 64,),
                requested_at=NOW,
            )
            first = await adapter.start(request)
            repeated = await adapter.start(request)
            persisted = await runtime.get(first.workflow_run_id)

            assert first == repeated
            assert persisted is not None
            assert persisted.run_id == first.workflow_run_id
            assert persisted.status.value == "queued"

            conflict = request.model_copy(update={"affected_scope": "600519.SH:1m"})
            with pytest.raises(Exception, match="idempotency"):
                await adapter.start(conflict)
        finally:
            await runtime.close()

    asyncio.run(exercise())


def test_lifespan_keeps_live_up_and_ready_down_when_workflow_runtime_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_runtime() -> WorkflowCommandRuntime:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        server,
        "create_workflow_command_runtime_from_environment",
        fail_runtime,
    )

    async def exercise() -> None:
        async with server.lifespan(server.finance_app):
            live_response = await server.live(_request(b""))
            ready_response = await server.ready(_request(b""))
            assert live_response.status_code == 200
            assert ready_response.status_code == 503
            assert _payload(ready_response)["readiness_reason"] == (
                "DQ_WORKFLOW_RUNTIME_UNAVAILABLE"
            )

    asyncio.run(exercise())


def test_readiness_coalesces_concurrent_probes_and_reuses_short_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def probe() -> tuple[bool, str]:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return True, "READY"

    monkeypatch.setattr(server, "_probe_readiness", probe)
    monkeypatch.setattr(server, "_readiness_cache", None)
    monkeypatch.setattr(server.settings, "readiness_cache_ttl_seconds", 10.0)

    async def exercise() -> None:
        results = await asyncio.gather(*(server._readiness() for _ in range(8)))
        cached = await server._readiness()
        assert results == [(True, "READY")] * 8
        assert cached == (True, "READY")

    asyncio.run(exercise())
    assert calls == 1


def test_readiness_timeout_returns_stable_unavailable_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def blocked_probe() -> tuple[bool, str]:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    monkeypatch.setattr(server, "_probe_readiness", blocked_probe)
    monkeypatch.setattr(server, "_readiness_cache", None)
    monkeypatch.setattr(server.settings, "readiness_probe_timeout_seconds", 0.01)

    result = asyncio.run(server._readiness())

    assert result == (False, "READINESS_PROBE_TIMEOUT")


def test_lifespan_owns_one_workflow_runtime_and_closes_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RuntimeStub:
        def __init__(self) -> None:
            self.closed = False

        async def create(
            self,
            command: WorkflowCreateCommand,
        ) -> WorkflowCreationReceipt:
            del command
            raise AssertionError("create is not expected")

        async def get(self, run_id: str) -> WorkflowRun | None:
            del run_id
            return None

        async def close(self) -> None:
            self.closed = True

    runtime = RuntimeStub()
    calls = 0

    def build_runtime(*, database_url: str | None = None) -> WorkflowCommandRuntime:
        nonlocal calls
        del database_url
        calls += 1
        return cast(WorkflowCommandRuntime, runtime)

    monkeypatch.setattr(
        server,
        "create_workflow_command_runtime_from_environment",
        build_runtime,
    )

    async def exercise() -> None:
        async with server.lifespan(server.finance_app):
            assert server.workflow_commands is runtime
            assert calls == 1
            first = await server.live(_request(b""))
            second = await server.live(_request(b""))
            assert first.status_code == second.status_code == 200
            assert runtime.closed is False
        assert runtime.closed is True

    asyncio.run(exercise())


def _request(query_string: bytes) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/market/test",
            "query_string": query_string,
            "headers": [],
            "server": ("testserver", 80),
            "client": ("testclient", 123),
            "scheme": "http",
        }
    )


def _payload(response: JSONResponse) -> Any:
    return json.loads(bytes(response.body))
