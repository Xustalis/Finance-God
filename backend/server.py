"""Serve the Finance-God desktop prototype and normalized PandaData APIs."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC
import logging
import os
from pathlib import Path
from threading import Lock
from uuid import uuid4

from dotenv import load_dotenv
from finance_god.market_data import (
    DQTriggerRequest,
    DQWorkflowReceipt,
    MarketDataApplication,
    MarketDataError,
    MarketDataService,
    capability_catalog_summary,
)
from finance_god.api.workspace_routes import create_workspace_routes
from finance_god.api.simulation import create_simulation_routes
from finance_god.application.ledger_service import SimulationLedgerService
from finance_god.application.ports import Clock as LedgerClock, IdGenerator as LedgerIdGenerator
from finance_god.domain.simulation_rules import SIMULATION_RULE_VERSION
from finance_god.infrastructure.persistence.uow import (
    SqlAlchemyUnitOfWork,
    create_session_factory,
)
from finance_god.infrastructure.simulation_wiring import (
    SystemClock,
    UuidIdGenerator,
    build_simulation_services,
)
from finance_god.orchestration.workflows import (
    WorkflowCommandPort,
    WorkflowCommandRuntime,
    WorkflowCreateCommand,
    WorkflowKey,
    create_workflow_command_runtime_from_environment,
)
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

_BACKEND_ROOT = Path(__file__).resolve().parent
_PROJECT_ROOT = _BACKEND_ROOT.parent
_LOGGER = logging.getLogger(__name__)
load_dotenv(_BACKEND_ROOT / ".env", override=False)

market_data: MarketDataService | None = None
market_application: MarketDataApplication | None = None
workflow_commands: WorkflowCommandPort | None = None
workflow_runtime: WorkflowCommandRuntime | None = None
workflow_runtime_readiness_reason: str | None = None
workspace_engine: AsyncEngine | None = None
workspace_sessions: async_sessionmaker[AsyncSession] | None = None
simulation_execution = None
simulation_accounts = None
_service_lock = Lock()


class WorkflowCommandDQAdapter:
    """Map the Panda quality intent to the public durable workflow command."""

    def __init__(self, commands: WorkflowCommandPort) -> None:
        self._commands = commands

    async def start(self, request: DQTriggerRequest) -> DQWorkflowReceipt:
        command = WorkflowCreateCommand.model_validate(
            {
                "idempotency_key": request.idempotency_key,
                "workflow_key": WorkflowKey.DATA_QUALITY_REVIEW,
                "request_intent": (
                    "PandaData quality gate requested diagnostic review."
                ),
                "owner_id": "system:pandadata-quality-gate",
                "scope": {
                    "affected_scope": request.affected_scope,
                    "quality_policy": request.policy_version,
                    "diagnostic_set": request.idempotency_key,
                },
                "input_versions": [
                    {
                        "object_type": "market_data_quality_decision",
                        "object_id": request.affected_scope,
                        "version": request.idempotency_key,
                    }
                ],
                "requested_at": request.requested_at.astimezone(UTC),
                "permissions": ["market_data:read"],
            }
        )
        receipt = await self._commands.create(command)
        if receipt.idempotency_key != request.idempotency_key:
            raise ValueError("workflow creation receipt idempotency key mismatch")
        return DQWorkflowReceipt(
            workflow_run_id=receipt.run.run_id,
            idempotency_key=receipt.idempotency_key,
        )


def _services() -> tuple[MarketDataService, MarketDataApplication]:
    global market_data, market_application
    if market_data is not None and market_application is not None:
        return market_data, market_application
    with _service_lock:
        if market_data is None:
            market_data = MarketDataService.from_environment()
        if market_application is None:
            market_application = MarketDataApplication(
                market_data,
                dq_workflow=(
                    WorkflowCommandDQAdapter(workflow_commands)
                    if workflow_commands is not None
                    else None
                ),
            )
    return market_data, market_application


def _workspace_session() -> AsyncSession:
    global workspace_engine, workspace_sessions
    if workspace_sessions is not None:
        return workspace_sessions()
    database_url = os.getenv("FINANCE_GOD_DATABASE_URL")
    if not database_url:
        raise RuntimeError("FINANCE_GOD_DATABASE_URL is required for workspace APIs")
    with _service_lock:
        if workspace_sessions is None:
            workspace_engine, workspace_sessions = create_session_factory(database_url)
    assert workspace_sessions is not None
    return workspace_sessions()


def _workspace_owner(_: Request) -> str:
    """Resolve the single simulated desktop identity from server configuration."""
    owner_id = os.getenv("FINANCE_GOD_WORKSPACE_OWNER_ID", "").strip()
    if not owner_id:
        raise PermissionError("workspace identity is not configured")
    return owner_id


@asynccontextmanager
async def lifespan(_: Starlette) -> AsyncIterator[None]:
    global market_data, market_application
    global workflow_commands, workflow_runtime
    global workflow_runtime_readiness_reason
    global workspace_engine, workspace_sessions
    global simulation_execution, simulation_accounts
    market_data = None
    market_application = None
    workflow_commands = None
    workflow_runtime = None
    workflow_runtime_readiness_reason = None
    simulation_execution = None
    simulation_accounts = None
    try:
        workflow_runtime = create_workflow_command_runtime_from_environment()
        workflow_commands = workflow_runtime
    except Exception as error:  # noqa: BLE001 - readiness reports stable safe reason
        _LOGGER.error(
            "workflow runtime initialization failed: %s",
            type(error).__name__,
        )
        workflow_runtime_readiness_reason = "DQ_WORKFLOW_RUNTIME_UNAVAILABLE"
    try:
        yield
    finally:
        runtime = workflow_runtime
        engine = workspace_engine
        workflow_commands = None
        workflow_runtime = None
        workspace_sessions = None
        workspace_engine = None
        simulation_execution = None
        simulation_accounts = None
        market_application = None
        market_data = None
        if runtime is not None:
            await runtime.close()
        if engine is not None:
            await engine.dispose()


def _json(model: object, *, status_code: int = 200) -> JSONResponse:
    if hasattr(model, "model_dump"):
        payload = model.model_dump(mode="json")
    else:
        payload = model
    return JSONResponse(payload, status_code=status_code)


async def live(_: Request) -> JSONResponse:
    return _json({"liveness": "live"}, status_code=200)


async def _readiness() -> tuple[bool, str]:
    if workflow_commands is None:
        return (
            False,
            workflow_runtime_readiness_reason or "DQ_WORKFLOW_RUNTIME_UNCONFIGURED",
        )
    try:
        await workflow_commands.get("readiness-probe")
    except Exception as error:  # noqa: BLE001 - workflow readiness is a safe boundary
        _LOGGER.error(
            "workflow readiness probe failed: %s",
            type(error).__name__,
        )
        return False, "DQ_WORKFLOW_DEPENDENCY_UNAVAILABLE"
    try:
        _service, application = _services()
        return await asyncio.to_thread(application.probe_readiness)
    except MarketDataError as error:
        return False, error.public_code.value
    except Exception:  # noqa: BLE001 - readiness must remain a safe boundary
        return False, "MARKET_DATA_INTERNAL_ERROR"


async def ready(_: Request) -> JSONResponse:
    is_ready, reason = await _readiness()
    return _json(
        {
            "readiness": "ready" if is_ready else "not_ready",
            "readiness_reason": reason,
        },
        status_code=200 if is_ready else 503,
    )


async def health(_: Request) -> JSONResponse:
    is_ready, reason = await _readiness()
    return _json(
        {
            "liveness": "live",
            "readiness": "ready" if is_ready else "not_ready",
            "readiness_reason": reason,
            "market_data": "PandaData",
            "account_mode": "simulation",
        },
        status_code=200 if is_ready else 503,
    )


async def quotes(request: Request) -> JSONResponse:
    symbols = request.query_params.get("symbols", "").split(",")
    try:
        _, application = _services()
        result = await application.quotes(symbols)
    except (ValueError, ValidationError):
        return _safe_error(
            code="MARKET_DATA_INVALID_REQUEST",
            message="The market-data request is invalid.",
            status_code=400,
        )
    except MarketDataError as error:
        return _json({"error": error.public_payload()}, status_code=502)
    except Exception:  # noqa: BLE001 - public HTTP error boundary
        return _internal_error()
    status_code = 200 if result.quotes else 502
    return _json(result, status_code=status_code)


async def bars(request: Request) -> JSONResponse:
    symbol = request.query_params.get("symbol", "")
    try:
        limit = int(request.query_params.get("limit", "80"))
        _, application = _services()
        result = await application.bars(
            symbol,
            limit=limit,
        )
    except (ValueError, ValidationError):
        return _safe_error(
            code="MARKET_DATA_INVALID_REQUEST",
            message="The market-data request is invalid.",
            status_code=400,
        )
    except MarketDataError as error:
        return _json({"error": error.public_payload()}, status_code=502)
    except Exception:  # noqa: BLE001 - public HTTP error boundary
        return _internal_error()
    return _json(
        {
            "provider": "PandaData",
            "symbol": symbol.upper(),
            "frequency": result.frequency,
            "bars": [item.model_dump(mode="json") for item in result.bars],
            "quality": result.quality.model_dump(mode="json"),
        }
    )


async def catalog(_request: Request) -> JSONResponse:
    try:
        service, _application = _services()
        items = await asyncio.to_thread(service.catalog)
        summary = capability_catalog_summary(items)
    except MarketDataError as error:
        return _json({"error": error.public_payload()}, status_code=502)
    except Exception:  # noqa: BLE001 - public HTTP error boundary
        return _internal_error()
    return _json(
        {
            "provider": "PandaData",
            "summary": summary,
            "datasets": items,
        }
    )


def _safe_error(
    *,
    code: str,
    message: str,
    status_code: int,
) -> JSONResponse:
    return _json(
        {
            "error": {
                "code": code,
                "message": message,
                "trace_id": uuid4().hex,
            }
        },
        status_code=status_code,
    )


def _internal_error() -> JSONResponse:
    return _safe_error(
        code="MARKET_DATA_INTERNAL_ERROR",
        message="The market-data request failed internally.",
        status_code=500,
    )


async def reject_websocket(websocket: WebSocket) -> None:
    """Reject unsupported upgrade probes before they reach StaticFiles."""
    await websocket.close(code=1008, reason="Finance-God prototype uses HTTP polling")


def _simulation_routes() -> list:
    """Lazily build and cache simulation execution + account services."""
    global simulation_execution, simulation_accounts
    if simulation_execution is not None and simulation_accounts is not None:
        return create_simulation_routes(
            execution=simulation_execution,
            accounts=simulation_accounts,
        )
    try:
        clock = SystemClock()
        ids = UuidIdGenerator()

        class _StaticRuleCatalog:
            simulation_rule_version = SIMULATION_RULE_VERSION

        uow_factory = lambda: SqlAlchemyUnitOfWork(_workspace_session)
        ledger = SimulationLedgerService(
            uow_factory=uow_factory,
            clock=clock,
            ids=ids,
            rules=_StaticRuleCatalog(),
        )
        simulation_execution, simulation_accounts = build_simulation_services(
            uow_factory=uow_factory,
            simulation_session_factory=_workspace_session,
            ledger=ledger,
        )
        _LOGGER.info("simulation services initialized successfully")
    except Exception as error:  # noqa: BLE001
        _LOGGER.error(
            "simulation service initialization failed: %s: %s",
            type(error).__name__,
            error,
        )
        return []
    return create_simulation_routes(
        execution=simulation_execution,
        accounts=simulation_accounts,
    )


finance_routes = [
    Route("/live", live),
    Route("/ready", ready),
    Route("/health", health),
    Route("/market/quotes", quotes),
    Route("/market/bars", bars),
    Route("/market/catalog", catalog),
    Mount(
        "/workspace",
        routes=create_workspace_routes(
            session_factory=_workspace_session,
            owner_resolver=_workspace_owner,
        ),
        name="workspace",
    ),
    Mount(
        "/simulation",
        routes=_simulation_routes(),
        name="simulation",
    ),
]

finance_app = Starlette(debug=False, routes=finance_routes)

routes = [
    Mount("/api", finance_app, name="finance-api"),
    WebSocketRoute("/{path:path}", reject_websocket),
    Mount(
        "/",
        app=StaticFiles(
            directory=_PROJECT_ROOT / "prototype",
            html=True,
            check_dir=False,
        ),
        name="prototype",
    ),
]

app = Starlette(debug=False, routes=routes, lifespan=lifespan)
