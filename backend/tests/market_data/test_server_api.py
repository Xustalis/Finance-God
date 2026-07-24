from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
import server
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from finance_god.market_data import (
    CATALOG,
    DQTriggerRequest,
    ErrorKind,
    MarketDataError,
)
from finance_god.orchestration.workflows import (
    WorkflowCreateCommand,
    WorkflowCommandRuntime,
    WorkflowCreationReceipt,
    WorkflowRun,
    create_workflow_command_runtime_from_environment,
)
from starlette.requests import Request
from starlette.responses import JSONResponse

from .conftest import NOW

BACKEND_ROOT = Path(__file__).resolve().parents[2]


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


def test_market_api_returns_stable_safe_errors_without_raw_exception_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, "market_data", StubService())
    monkeypatch.setattr(server, "market_application", FailingApplication())
    quotes = asyncio.run(server.quotes(_request(b"symbols=000001.SZ")))
    bars = asyncio.run(server.bars(_request(b"symbol=000001.SZ")))
    invalid = asyncio.run(server.bars(_request(b"symbol=000001.SZ&limit=bad")))
    live = asyncio.run(server.live(_request(b"")))
    ready = asyncio.run(server.ready(_request(b"")))
    health = asyncio.run(server.health(_request(b"")))
    quote_payload = _payload(quotes)
    bars_payload = _payload(bars)
    invalid_payload = _payload(invalid)
    live_payload = _payload(live)
    ready_payload = _payload(ready)
    health_payload = _payload(health)
    rendered = json.dumps(
        [quote_payload, bars_payload, invalid_payload],
        ensure_ascii=False,
    )

    assert quotes.status_code == 502
    assert quote_payload["error"]["code"] == "MARKET_DATA_PERMISSION_DENIED"
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
        for payload in (quote_payload, bars_payload, invalid_payload)
    )


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
        async with server.lifespan(server.app):
            live_response = await server.live(_request(b""))
            ready_response = await server.ready(_request(b""))
            assert live_response.status_code == 200
            assert ready_response.status_code == 503
            assert _payload(ready_response)["readiness_reason"] == (
                "DQ_WORKFLOW_RUNTIME_UNAVAILABLE"
            )

    asyncio.run(exercise())


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

    def build_runtime() -> WorkflowCommandRuntime:
        nonlocal calls
        calls += 1
        return cast(WorkflowCommandRuntime, runtime)

    monkeypatch.setattr(
        server,
        "create_workflow_command_runtime_from_environment",
        build_runtime,
    )

    async def exercise() -> None:
        async with server.lifespan(server.app):
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
