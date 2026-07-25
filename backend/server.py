"""Finance API composition mounted exclusively by ``app.main:app``."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Lock
from time import monotonic
from typing import TYPE_CHECKING
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from app.config import settings
from app.core.security import resolve_active_user
from app.db.session import create_db_session
from app.models.profile import DirectionRecommendation, InvestmentProfile
from finance_god.api.agent_learning_routes import create_agent_learning_routes
from finance_god.api.agent_routes import (
    AgentRuntimeUnavailable,
    create_agent_routes,
)
from finance_god.api.auth import AuthenticationError
from finance_god.api.crawler_routes import create_crawler_routes
from finance_god.api.desk_routes import create_desk_routes, project_suitability_profile
from finance_god.api.event_routes import create_event_routes
from finance_god.api.evidence_routes import create_evidence_routes
from finance_god.api.mandate_routes import create_mandate_routes
from finance_god.api.simulation import create_simulation_routes
from finance_god.api.trade_episode_routes import create_trade_episode_routes
from finance_god.api.trade_plan_routes import create_trade_plan_routes
from finance_god.api.workflow_routes import (
    WorkflowRuntimeUnavailable,
    create_workflow_routes,
)
from finance_god.api.workspace_routes import create_workspace_routes
from finance_god.application.agent_learning_summary import AgentLearningSummaryReader
from finance_god.application.candidate_service import (
    CandidateResponse,
    CandidateScoringService,
    candidates_for_profile,
)
from finance_god.application.decision_inbox import DecisionInboxService
from finance_god.application.evidence_service import EvidenceService
from finance_god.application.idempotency import (
    canonical_request_hash,
    stable_idempotency_key,
)
from finance_god.application.ledger_service import SimulationLedgerService
from finance_god.application.mandate_service import MandateService
from finance_god.application.market_alert_notifications import (
    MarketAlertNotificationProjector,
)
from finance_god.application.market_poller import MarketPoller
from finance_god.application.portfolio_query import PortfolioQueryService
from finance_god.application.simulation_clock import SimulationClockService
from finance_god.application.trade_plan_service import TradePlanService
from finance_god.application.workflow_worker import MarketAlertContext, WorkflowWorker
from finance_god.crawler.service import get_crawler_service
from finance_god.domain import Notification, VersionReference
from finance_god.domain.simulation_rules import SIMULATION_RULE_VERSION
from finance_god.infrastructure.mandate_provider import (
    PersistentAuthorizationProvider,
)
from finance_god.infrastructure.persistence.market_monitor_repository import (
    MarketMonitorUnitOfWork,
)
from finance_god.infrastructure.persistence.uow import SqlAlchemyUnitOfWork
from finance_god.infrastructure.persistence.workflow_uow import WorkflowUnitOfWork
from finance_god.infrastructure.persistence.workspace_models import UserMarketFocusRow
from finance_god.infrastructure.persistence.workspace_uow import WorkspaceUnitOfWork
from finance_god.infrastructure.simulation_wiring import (
    SystemClock,
    UuidIdGenerator,
    build_simulation_services,
)
from finance_god.market_data import (
    DQTriggerRequest,
    DQWorkflowReceipt,
    MarketDataApplication,
    MarketDataError,
    MarketDataService,
    MarketQuote,
    QuoteBatch,
    capability_catalog_summary,
)
from finance_god.market_data.errors import ErrorKind
from finance_god.orchestration.multi_agent import MultiAgentRuntime
from finance_god.orchestration.workflows import (
    WorkflowCommandPort,
    WorkflowCommandRuntime,
    WorkflowCreateCommand,
    WorkflowKey,
    create_workflow_command_runtime_from_environment,
)
from finance_god.trade_review import TradeReviewService

if TYPE_CHECKING:
    from finance_god.learning.context import VerifiedKnowledgeReader

_LOGGER = logging.getLogger(__name__)

market_data: MarketDataService | None = None
market_application: MarketDataApplication | None = None
workflow_commands: WorkflowCommandPort | None = None
workflow_runtime: WorkflowCommandRuntime | None = None
workflow_runtime_readiness_reason: str | None = None
simulation_execution = None
simulation_accounts = None
agent_runtime = None
agent_runtime_reason: str | None = None
learning_context_reader: VerifiedKnowledgeReader | None = None
market_poller_task: asyncio.Task[None] | None = None
market_poller_stop: asyncio.Event | None = None
workflow_worker_task: asyncio.Task[None] | None = None
workflow_worker_stop: asyncio.Event | None = None
workflow_worker_wakeup: asyncio.Event | None = None
_agent_lock = Lock()
_learning_lock = Lock()
_service_lock = Lock()
_desk_decision_contexts: dict[str, tuple[str, str, float]] = {}
_DESK_DECISION_CONTEXT_TTL_SECONDS = 1_800.0
_readiness_cache: tuple[float, bool, str] | None = None
_readiness_lock = asyncio.Lock()
_simulation_next_session_cache: dict[str, datetime] = {}


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
    return create_db_session()


async def _record_market_focus(
    owner_user_id: str, symbol: str, updated_at: datetime
) -> None:
    async with create_db_session() as session, session.begin():
        await session.merge(
            UserMarketFocusRow(
                owner_user_id=owner_user_id,
                symbol=symbol,
                updated_at=updated_at,
            )
        )


def _mandate_service() -> MandateService:
    """Build the mandate application service over the workspace session."""
    return MandateService(
        session_factory=_workspace_session,
        clock=SystemClock(),
        ids=UuidIdGenerator(),
    )


async def _authenticated_owner(request: Request) -> str:
    """Resolve the owner from a signed token and current active user record."""
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AuthenticationError("valid Bearer authentication is required")
    async with create_db_session() as session:
        user = await resolve_active_user(token, session)
    if user is None:
        raise AuthenticationError("valid Bearer authentication is required")
    return user.id


@asynccontextmanager
async def lifespan(_: Starlette) -> AsyncIterator[None]:
    global market_data, market_application
    global workflow_commands, workflow_runtime
    global workflow_runtime_readiness_reason
    global simulation_execution, simulation_accounts
    global agent_runtime, agent_runtime_reason
    global learning_context_reader
    global market_poller_task, market_poller_stop
    global workflow_worker_task, workflow_worker_stop, workflow_worker_wakeup
    global _readiness_cache
    _readiness_cache = None
    market_data = None
    market_application = None
    workflow_commands = None
    workflow_runtime = None
    workflow_runtime_readiness_reason = None
    simulation_execution = None
    simulation_accounts = None
    agent_runtime = None
    agent_runtime_reason = None
    learning_context_reader = None
    market_poller_task = None
    market_poller_stop = None
    workflow_worker_task = None
    workflow_worker_stop = None
    workflow_worker_wakeup = None
    try:
        workflow_runtime = create_workflow_command_runtime_from_environment(
            database_url=settings.database_url
        )
        workflow_commands = workflow_runtime
    except Exception as error:  # noqa: BLE001 - readiness reports stable safe reason
        _LOGGER.error(
            "workflow runtime initialization failed: %s",
            type(error).__name__,
        )
        workflow_runtime_readiness_reason = "DQ_WORKFLOW_RUNTIME_UNAVAILABLE"
    market_poller_stop, market_poller_task = _start_market_poller()
    (
        workflow_worker_stop,
        workflow_worker_wakeup,
        workflow_worker_task,
    ) = _start_workflow_worker()
    try:
        yield
    finally:
        runtime = workflow_runtime
        stop_event = market_poller_stop
        poller_task = market_poller_task
        worker_stop = workflow_worker_stop
        worker_task = workflow_worker_task
        workflow_commands = None
        workflow_runtime = None
        simulation_execution = None
        simulation_accounts = None
        market_application = None
        market_data = None
        agent_runtime = None
        agent_runtime_reason = None
        learning_context_reader = None
        market_poller_task = None
        market_poller_stop = None
        workflow_worker_task = None
        workflow_worker_stop = None
        workflow_worker_wakeup = None
        if stop_event is not None:
            stop_event.set()
        if worker_stop is not None:
            worker_stop.set()
        if poller_task is not None:
            try:
                await poller_task
            except Exception:  # noqa: BLE001 - shutdown must not raise
                _LOGGER.warning("market poller task did not shut down cleanly")
        if worker_task is not None:
            try:
                await worker_task
            except Exception:  # noqa: BLE001 - shutdown must not raise
                _LOGGER.warning("workflow worker task did not shut down cleanly")
        if runtime is not None:
            await runtime.close()


def _json(model: object, *, status_code: int = 200) -> JSONResponse:
    if hasattr(model, "model_dump"):
        payload = model.model_dump(mode="json")
    else:
        payload = model
    return JSONResponse(payload, status_code=status_code)


async def live(_: Request) -> JSONResponse:
    return _json({"liveness": "live"}, status_code=200)


async def _probe_readiness() -> tuple[bool, str]:
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
        async with create_db_session() as session:
            connection = await session.connection()
            table_names = set(
                await connection.run_sync(
                    lambda sync_connection: inspect(
                        sync_connection
                    ).get_table_names()
                )
            )
    except Exception as error:  # noqa: BLE001 - stable readiness boundary
        _LOGGER.error(
            "database schema readiness probe failed: %s",
            type(error).__name__,
        )
        return False, "DATABASE_SCHEMA_UNAVAILABLE"
    required_tables = {"market_snapshots", "market_alerts"}
    if not required_tables.issubset(table_names):
        return False, "DATABASE_SCHEMA_OUT_OF_DATE"
    if settings.market_poll_enabled and (
        market_poller_task is None or market_poller_task.done()
    ):
        return False, "MARKET_POLLER_UNAVAILABLE"
    if settings.workflow_worker_enabled and (
        workflow_worker_task is None or workflow_worker_task.done()
    ):
        return False, "WORKFLOW_WORKER_UNAVAILABLE"
    try:
        _service, application = _services()
        return await asyncio.to_thread(application.probe_readiness)
    except MarketDataError as error:
        return False, error.public_code.value
    except Exception:  # noqa: BLE001 - readiness must remain a safe boundary
        return False, "MARKET_DATA_INTERNAL_ERROR"


async def _readiness() -> tuple[bool, str]:
    """Return a bounded, coalesced readiness result.

    The probe performs database reflection and upstream checks. A short cache
    prevents orchestrator and reverse-proxy health checks from multiplying that
    dependency load, while the lock collapses concurrent cache misses.
    """
    global _readiness_cache
    now = monotonic()
    cached = _readiness_cache
    if cached is not None and cached[0] > now:
        return cached[1], cached[2]

    async with _readiness_lock:
        now = monotonic()
        cached = _readiness_cache
        if cached is not None and cached[0] > now:
            return cached[1], cached[2]
        try:
            result = await asyncio.wait_for(
                _probe_readiness(),
                timeout=settings.readiness_probe_timeout_seconds,
            )
        except TimeoutError:
            _LOGGER.error(
                "readiness probe exceeded %.2fs",
                settings.readiness_probe_timeout_seconds,
            )
            result = (False, "READINESS_PROBE_TIMEOUT")
        _readiness_cache = (
            now + settings.readiness_cache_ttl_seconds,
            result[0],
            result[1],
        )
        return result


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


async def market_overview(request: Request) -> JSONResponse:
    symbols = request.query_params.get("symbols", "").split(",")
    try:
        service, application = _services()
        batch = None
        batch_error: MarketDataError | None = None
        try:
            batch = await application.quotes(symbols)
        except MarketDataError as error:
            batch_error = error
        _INDEX_NAMES = {
            "000001.SH": "上证指数",
            "399001.SZ": "深证成指",
            "000300.SH": "沪深300",
        }
        quoted_symbols = {q.symbol for q in (batch.quotes if batch else ())}
        fallback_quotes = []
        for sym in symbols:
            sym_upper = sym.strip().upper()
            if not sym_upper or sym_upper in quoted_symbols:
                continue
            try:
                instrument = service.resolve(sym_upper)
            except Exception:  # noqa: BLE001
                continue
            if instrument.asset_class.value != "index":
                continue
            try:
                bar_result = await asyncio.to_thread(
                    service.read_bars, sym_upper, limit=2
                )
                if bar_result.bars:
                    latest = bar_result.bars[0]
                    previous_close = (
                        bar_result.bars[1].close if len(bar_result.bars) > 1 else None
                    )
                    change = (
                        latest.close - previous_close
                        if previous_close is not None
                        else None
                    )
                    change_pct = (
                        change / previous_close
                        if change is not None and previous_close
                        else None
                    )
                    fallback_quotes.append(
                        {
                            "symbol": instrument.symbol,
                            "name": _INDEX_NAMES.get(
                                instrument.symbol, instrument.symbol
                            ),
                            "asset_type": instrument.asset_class.value,
                            "market": instrument.market.value,
                            "currency": instrument.currency,
                            "last": str(latest.close),
                            "open": str(latest.open),
                            "high": str(latest.high),
                            "low": str(latest.low),
                            "previous_close": (
                                str(previous_close)
                                if previous_close is not None
                                else None
                            ),
                            "change": str(change) if change is not None else None,
                            "change_percent": (
                                str(change_pct) if change_pct is not None else None
                            ),
                            "volume": str(latest.volume),
                            "amount": (
                                str(latest.amount)
                                if latest.amount is not None
                                else None
                            ),
                            "provider": "PandaData",
                            "provider_time": latest.provider_time,
                            "retrieved_at": datetime.now(UTC).isoformat(),
                            "frequency": bar_result.frequency,
                            "freshness": latest.freshness,
                            "market_status": "released",
                            "session_alignment": "latest_released_session",
                            "source_endpoint": latest.source_endpoint,
                            "capability_version": latest.capability_version,
                            "instrument_master_identity": (
                                latest.instrument_master_identity
                            ),
                            "instrument_master_version": (
                                latest.instrument_master_version
                            ),
                            "trade_eligible": False,
                        }
                    )
            except Exception:  # noqa: BLE001 - fallback must not block
                continue
        all_quotes = [
            quote.model_dump(mode="json") for quote in (batch.quotes if batch else ())
        ] + fallback_quotes
        if not all_quotes:
            if batch_error is not None:
                return _json(
                    {"error": batch_error.public_payload()},
                    status_code=502,
                )
            return _safe_error(
                code="MARKET_DATA_UNAVAILABLE",
                message="No usable market snapshots were returned.",
                status_code=502,
            )
        warnings = []
        if batch_error is not None:
            warnings.append(
                {
                    "code": batch_error.public_payload()["code"],
                    "message": "部分标的实时快照不可用，已保留可验证的指数日线。",
                }
            )
        return _json({"data": {"quotes": all_quotes}, "warnings": warnings})
    except (ValueError, ValidationError):
        return _safe_error(
            code="MARKET_DATA_INVALID_REQUEST",
            message="The market overview request is invalid.",
            status_code=400,
        )
    except MarketDataError as error:
        return _json({"error": error.public_payload()}, status_code=502)
    except Exception:  # noqa: BLE001 - public HTTP error boundary
        return _internal_error()


async def bars(request: Request) -> JSONResponse:
    symbol = request.query_params.get("symbol", "")
    frequency_param = request.query_params.get("frequency", "")
    try:
        if "limit" in request.query_params:
            raise ValueError("client-defined bar limits are not supported")
        service, _application = _services()
        from finance_god.market_data.contracts import DataFrequency as DF

        freq_map = {"1m": DF.MINUTE_1, "daily": DF.DAILY, "1d": DF.DAILY}
        if frequency_param and frequency_param not in freq_map:
            raise ValueError("unsupported bar frequency")
        frequency_override = freq_map.get(frequency_param) if frequency_param else None
        limit = 1_000 if frequency_override is DF.DAILY else 500
        result = await asyncio.to_thread(
            service.read_bars,
            symbol,
            limit=limit,
            frequency_override=frequency_override,
        )
        if not result.bars:
            raise MarketDataError(
                result.error_kind or ErrorKind.EMPTY,
                result.error_message or "PandaData returned no normalized bars",
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


async def information_facts(request: Request) -> JSONResponse:
    symbol = request.query_params.get("symbol", "")
    start_quarter = request.query_params.get("start_quarter")
    end_quarter = request.query_params.get("end_quarter")
    try:
        limit = int(request.query_params.get("limit", "20"))
        service, _application = _services()
        result = await asyncio.to_thread(
            service.read_information_facts,
            symbol,
            start_quarter=start_quarter or "",
            end_quarter=end_quarter or "",
            limit=limit,
        )
    except (ValueError, ValidationError):
        return _safe_error(
            code="MARKET_DATA_INVALID_REQUEST",
            message="The information-fact request is invalid.",
            status_code=400,
        )
    except MarketDataError as error:
        if (
            settings.market_reference_mock_fallback
            and error.kind is not ErrorKind.CAPABILITY
        ):
            _LOGGER.warning(
                "Information reference source failed; serving labeled mock: %s",
                type(error).__name__,
            )
            return _mock_information_facts(symbol)
        return _json(
            {"error": error.public_payload()},
            status_code=422 if error.kind is ErrorKind.CAPABILITY else 502,
        )
    except Exception:  # noqa: BLE001 - public HTTP error boundary
        return _internal_error()
    return _json(result)


async def sentiment_facts(request: Request) -> JSONResponse:
    symbol = request.query_params.get("symbol", "")
    start_date = request.query_params.get("start_date")
    end_date = request.query_params.get("end_date")
    try:
        limit = int(request.query_params.get("limit", "60"))
        service, _application = _services()
        result = await asyncio.to_thread(
            service.read_sentiment_facts,
            symbol,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
        )
    except (ValueError, ValidationError):
        return _safe_error(
            code="MARKET_DATA_INVALID_REQUEST",
            message="The sentiment-fact request is invalid.",
            status_code=400,
        )
    except MarketDataError as error:
        if (
            settings.market_reference_mock_fallback
            and error.kind is not ErrorKind.CAPABILITY
        ):
            _LOGGER.warning(
                "Sentiment reference source failed; serving labeled mock: %s",
                type(error).__name__,
            )
            return _mock_sentiment_facts(symbol)
        return _json(
            {"error": error.public_payload()},
            status_code=422 if error.kind is ErrorKind.CAPABILITY else 502,
        )
    except Exception:  # noqa: BLE001 - public HTTP error boundary
        return _internal_error()
    return _json(result)


def _mock_information_facts(symbol: str) -> JSONResponse:
    generated_at = datetime.now(UTC).isoformat()
    normalized_symbol = symbol.upper() if symbol else "A_SHARE_MARKET"
    items = (
        ("模拟披露事实：上市公司定期报告安排", "公告"),
        ("模拟披露事实：主要指数成分调整进入观察期", "市场"),
        ("模拟披露事实：公开数据更新时间与口径差异", "研究"),
    )
    facts = [
        {
            "scope": f"mock-disclosure:{index}",
            "fields": [
                {"name": "title", "value": title},
                {
                    "name": "summary",
                    "value": "仅用于保持资讯模块可读，不构成市场事实或投资依据。",
                },
                {"name": "source", "value": "Finance-God Mock"},
                {"name": "url", "value": ""},
                {"name": "sector", "value": sector},
            ],
        }
        for index, (title, sector) in enumerate(items, start=1)
    ]
    return _json({
        "provider": "Finance-God Mock",
        "fact_kind": "company_disclosure",
        "symbol": normalized_symbol,
        "requested_at": generated_at,
        "generated_at": generated_at,
        "facts": facts,
        "news": [],
        "trade_eligible": False,
        "data_mode": "mock",
        "fallback_reason": "真实市场资讯源暂时不可用。",
    })


def _mock_sentiment_facts(symbol: str) -> JSONResponse:
    generated_at = datetime.now(UTC).isoformat()
    return _json({
        "provider": "Finance-God Mock",
        "fact_kind": "margin_balance",
        "symbol": symbol.upper() if symbol else "A_SHARE_MARKET",
        "requested_at": generated_at,
        "generated_at": generated_at,
        "facts": [
            {
                "scope": "mock-margin-balance",
                "fields": [
                    {"name": "融资余额", "value": None},
                    {"name": "来源", "value": "Finance-God Mock"},
                ],
            },
        ],
        "trade_eligible": False,
        "data_mode": "mock",
        "fallback_reason": "真实市场情绪源暂时不可用。",
    })


def _instrument_frequency(market: str, asset_class: str) -> str:
    """Display the bar frequency the market-data service uses for this asset."""
    if market == "CN" and asset_class == "equity":
        return "1min"
    return "daily"


def _supports_live_quote(market: str, asset_class: str) -> bool:
    """Only CN equities have a verified PandaData real-time snapshot endpoint.

    Instruments without a live quote are not surfaced by the software so users
    never search, select, or trade something the terminal cannot price.
    """
    return market == "CN" and asset_class == "equity"


async def instruments(request: Request) -> JSONResponse:
    """Search the authoritative instrument master (no PandaData credentials)."""
    query = request.query_params.get("q", "").strip().upper()
    try:
        service, _application = _services()
        master = service.instrument_master.all()
    except MarketDataError as error:
        return _json({"error": error.public_payload()}, status_code=502)
    except Exception:  # noqa: BLE001 - public HTTP error boundary
        return _internal_error()
    results = []
    for instrument in master:
        market = instrument.market.value
        asset_class = instrument.asset_class.value
        if not _supports_live_quote(market, asset_class):
            # Hide instruments the terminal cannot fetch live quotes for.
            continue
        haystack = (
            instrument.symbol,
            instrument.provider_symbol,
            market,
            asset_class,
            *instrument.aliases,
        )
        if query and not any(query in field.upper() for field in haystack):
            continue
        results.append(
            {
                "symbol": instrument.symbol,
                "provider_symbol": instrument.provider_symbol,
                "market": market,
                "asset_class": asset_class,
                "currency": instrument.currency,
                "aliases": list(instrument.aliases),
                "frequency": _instrument_frequency(market, asset_class),
                "simulation_supported": _supports_live_quote(market, asset_class),
            }
        )
    return _json(
        {
            "provider": "PandaData",
            "query": query,
            "instrument_master_identity": service.instrument_master.identity,
            "instrument_master_version": service.instrument_master.version,
            "instruments": results,
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


def _simulation_uow_factory() -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(_workspace_session)


def _workflow_command_provider() -> WorkflowCommandPort:
    if workflow_commands is None:
        raise WorkflowRuntimeUnavailable("durable workflow runtime is unavailable")
    return workflow_commands


def _workflow_definition(workflow_key: str):
    if workflow_runtime is None:
        raise WorkflowRuntimeUnavailable("durable workflow runtime is unavailable")
    return workflow_runtime.definition(workflow_key)


async def _desk_capability_probe() -> dict[str, bool]:
    """Report only capabilities backed by a live runtime dependency.

    Config flags alone never flip True. workflow_create requires a durable
    command port that answers a probe; workflow_worker requires the in-process
    worker task to be running; market_data requires a successful readiness probe.
    """
    workflow_create = False
    if workflow_commands is not None:
        try:
            await workflow_commands.get("readiness-probe")
            workflow_create = True
        except Exception:  # noqa: BLE001 - unavailable runtime must stay False
            _LOGGER.error(
                "desk capability probe: workflow runtime unavailable (%s)",
                type(workflow_commands).__name__,
            )
            workflow_create = False

    worker_task = workflow_worker_task
    workflow_worker = (
        settings.workflow_worker_enabled
        and worker_task is not None
        and not worker_task.done()
    )

    market_data_ready = False
    try:
        _service, application = _services()
        market_data_ready, _reason = await asyncio.to_thread(application.probe_readiness)
    except Exception:  # noqa: BLE001 - market probe must not break bootstrap
        market_data_ready = False

    agent_answer = False
    try:
        await _agent_runtime_provider()
        agent_answer = True
    except AgentRuntimeUnavailable:
        agent_answer = False

    return {
        "workflow_create": workflow_create,
        "workflow_worker": bool(workflow_worker),
        "workflow_list": workflow_create,
        "workflow_cancel": workflow_create,
        "workflow_retry": workflow_create,
        "workflow_resume": workflow_create,
        "agent_answer": agent_answer,
        "market_data": bool(market_data_ready),
        "ui_actions": True,
        "settings_excluded": True,
        "workflow_claim": False,
        "order_submit": False,
        "order_cancel": False,
        "fund_transfer": False,
    }


async def _candidate_quotes(symbols: list[str]):
    _, application = _services()
    return await application.quotes(symbols)


async def _workflow_market_context_quotes(symbols: list[str]) -> QuoteBatch:
    """Return a research snapshot, deriving index values from verified daily bars.

    PandaData does not expose a verified real-time snapshot endpoint for indices.
    The workflow still needs a source-stamped point-in-time value, so indices use
    the latest two released daily bars instead of pretending the equity endpoint
    supports them.
    """
    batch = await _candidate_quotes(symbols)
    missing = [
        symbol
        for symbol in symbols
        if symbol not in {quote.symbol for quote in batch.quotes}
        and batch.errors.get(symbol)
        == "asset class has no verified snapshot endpoint"
    ]
    if not missing:
        return batch

    _, application = _services()
    derived: list[MarketQuote] = []
    remaining_errors = dict(batch.errors)
    end = datetime.now(ZoneInfo("Asia/Shanghai"))
    start_date = (end - timedelta(days=45)).strftime("%Y%m%d")
    end_date = end.strftime("%Y%m%d")
    for symbol in missing:
        history = await application.historical_daily_bars(
            symbol,
            start_date=start_date,
            end_date=end_date,
            limit=45,
        )
        if len(history.bars) < 2:
            remaining_errors[symbol] = (
                "index snapshot requires at least two released daily bars"
            )
            continue
        previous, latest = history.bars[-2:]
        change = latest.close - previous.close
        change_percent = (
            change / previous.close if previous.close != 0 else None
        )
        derived.append(
            MarketQuote(
                symbol=symbol,
                name=symbol,
                asset_type="index",
                market="CN",
                currency="CNY",
                last=latest.close,
                open=latest.open,
                high=latest.high,
                low=latest.low,
                previous_close=previous.close,
                change=change,
                change_percent=change_percent,
                volume=latest.volume,
                amount=latest.amount,
                provider="PandaData",
                provider_time=latest.provider_time,
                retrieved_at=datetime.now(UTC),
                frequency=history.frequency,
                freshness=latest.freshness,
                session_alignment="latest_released_session",
                market_status="released",
                source_endpoint=latest.source_endpoint,
                capability_version=latest.capability_version,
                instrument_master_identity=latest.instrument_master_identity,
                instrument_master_version=latest.instrument_master_version,
            )
        )
        remaining_errors.pop(symbol, None)
    return QuoteBatch(
        requested_at=batch.requested_at,
        cache_hit=batch.cache_hit,
        quotes=(*batch.quotes, *derived),
        errors=remaining_errors,
        diagnostics=batch.diagnostics,
        quality=batch.quality,
    )


async def _workflow_market_history(
    symbol: str,
    *,
    start_date: str,
    end_date: str,
    limit: int,
):
    _, application = _services()
    return await application.historical_daily_bars(
        symbol,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )


async def _workflow_information_facts(
    symbol: str,
    *,
    start_quarter: str,
    end_quarter: str,
    limit: int,
):
    _, application = _services()
    return await application.information_facts(
        symbol,
        start_quarter=start_quarter,
        end_quarter=end_quarter,
        limit=limit,
    )


async def _workflow_sentiment_facts(
    symbol: str,
    *,
    start_date: str,
    end_date: str,
    limit: int,
):
    _, application = _services()
    return await application.sentiment_facts(
        symbol,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )


async def _workflow_crawler_context():
    return await get_crawler_service().get_full_report(news_limit=20)


async def _market_alert_context(symbol: str) -> MarketAlertContext:
    async with _market_monitor_uow() as uow:
        snapshot = await uow.monitor.get_snapshot(symbol)
        latest_alert = await uow.monitor.latest_alert(symbol)
    return MarketAlertContext(
        snapshot=snapshot,
        latest_alert=latest_alert,
        observed_at=datetime.now(UTC),
    )


def _market_monitor_uow() -> MarketMonitorUnitOfWork:
    return MarketMonitorUnitOfWork(_workspace_session)


def _market_poll_universe() -> list[str]:
    """Derive the bounded poll universe from configuration or CN equities."""
    configured = settings.market_poll_universe
    if configured:
        symbols = [item.strip().upper() for item in configured.split(",")]
        return [symbol for symbol in symbols if symbol]
    service, _application = _services()
    return [
        instrument.symbol
        for instrument in service.instrument_master.all()
        if _supports_live_quote(
            instrument.market.value,
            instrument.asset_class.value,
        )
    ]


async def snapshots(_request: Request) -> JSONResponse:
    """Return server-cached market snapshots with upstream metadata."""
    try:
        async with _market_monitor_uow() as uow:
            rows = await uow.monitor.list_snapshots()
    except Exception:  # noqa: BLE001 - public HTTP error boundary
        return _internal_error()
    return _json(
        {
            "provider": "PandaData",
            "poll_interval_seconds": settings.market_poll_interval_seconds,
            "alert_threshold": settings.market_alert_threshold,
            "snapshots": [row.model_dump(mode="json") for row in rows],
        }
    )


async def alerts(request: Request) -> JSONResponse:
    """Return the most recent global market alerts."""
    try:
        limit = int(request.query_params.get("limit", "50"))
    except ValueError:
        limit = 50
    limit = max(1, min(limit, 200))
    try:
        async with _market_monitor_uow() as uow:
            rows = await uow.monitor.list_alerts(limit=limit)
    except Exception:  # noqa: BLE001 - public HTTP error boundary
        return _internal_error()
    return _json(
        {
            "provider": "PandaData",
            "alerts": [row.model_dump(mode="json") for row in rows],
        }
    )


def _start_market_poller() -> tuple[asyncio.Event | None, asyncio.Task[None] | None]:
    """Start the market poller when enabled and a priceable universe exists."""
    if not settings.market_poll_enabled:
        return None, None
    try:
        universe = _market_poll_universe()
    except Exception as error:  # noqa: BLE001 - poller cannot block API startup
        detail = getattr(error, 'internal_message', str(error))
        _LOGGER.error(
            "market poll universe derivation failed: %s: %s",
            type(error).__name__,
            detail,
        )
        return None, None
    if not universe:
        _LOGGER.info("market poller idle: no priceable instruments in universe")
        return None, None
    escalate = settings.market_alert_escalate_threshold

    async def evaluate_protective_strategies(snapshot) -> None:
        global simulation_execution
        if simulation_execution is None:
            _simulation_routes()
        if simulation_execution is None:
            raise RuntimeError("simulation execution service is unavailable")
        await simulation_execution.evaluate_protective_strategies(
            instrument_id=snapshot.symbol,
            trusted_price=snapshot.last,
            market_evidence=VersionReference(
                object_type="market_quote",
                object_id=snapshot.symbol,
                version=snapshot.provider_time,
            ),
        )

    poller = MarketPoller(
        quotes_provider=_candidate_quotes,
        uow_factory=_market_monitor_uow,
        threshold=Decimal(str(settings.market_alert_threshold)),
        escalate_threshold=(
            Decimal(str(escalate)) if escalate is not None else None
        ),
        snapshot_observer=evaluate_protective_strategies,
        alert_dispatcher=MarketAlertNotificationProjector(
            _workspace_session
        ).dispatch_pending,
    )
    stop_event = asyncio.Event()
    task = asyncio.create_task(
        poller.run_forever(
            symbols=universe,
            interval_seconds=settings.market_poll_interval_seconds,
            stop_event=stop_event,
        )
    )
    _LOGGER.info(
        "market poller started over %d instrument(s) at %.0fs interval",
        len(universe),
        settings.market_poll_interval_seconds,
    )
    return stop_event, task


def _start_workflow_worker() -> tuple[
    asyncio.Event | None,
    asyncio.Event | None,
    asyncio.Task[None] | None,
]:
    """Start the Workflow Worker when enabled and the runtime is available."""
    if not settings.workflow_worker_enabled:
        return None, None, None
    runtime = workflow_runtime
    if runtime is None:
        _LOGGER.info("workflow worker idle: workflow runtime unavailable")
        return None, None, None
    session_factory = runtime.session_factory
    registry = runtime.registry

    def uow_factory() -> WorkflowUnitOfWork:
        return WorkflowUnitOfWork(session_factory)

    wake_event = asyncio.Event()
    worker = WorkflowWorker(
        uow_factory=uow_factory,
        runtime_provider=_agent_runtime_provider,
        evidence_recorder=_record_workflow_evidence,
        profile_provider=_workflow_profile_context,
        candidate_provider=_workflow_candidates,
        market_context_provider=_workflow_market_context_quotes,
        market_history_provider=_workflow_market_history,
        information_facts_provider=_workflow_information_facts,
        sentiment_facts_provider=_workflow_sentiment_facts,
        crawler_context_provider=_workflow_crawler_context,
        market_alert_context_provider=_market_alert_context,
        portfolio_provider=_workflow_portfolio,
        trade_plan_provider=_workflow_trade_plan,
        order_draft_provider=_workflow_order_draft,
        order_draft_review_provider=_workflow_order_draft_review,
        registry=registry,
        batch_size=settings.workflow_worker_batch_size,
        wake_event=wake_event,
    )
    stop_event = asyncio.Event()
    task = asyncio.create_task(
        worker.run_forever(
            interval_seconds=settings.workflow_worker_interval_seconds,
            stop_event=stop_event,
        )
    )
    _LOGGER.info(
        "workflow worker started at %.1fs interval (batch=%d)",
        settings.workflow_worker_interval_seconds,
        settings.workflow_worker_batch_size,
    )
    return stop_event, wake_event, task


async def _workflow_portfolio(owner_id: str):
    return await PortfolioQueryService(
        uow_factory=_simulation_uow_factory,
        clock=SystemClock(),
        rule_version=SIMULATION_RULE_VERSION,
    ).positions(owner_id=owner_id)


async def _workflow_trade_plan(
    owner_id: str,
    symbol: str,
    idempotency_key: str,
):
    return await _trade_plan_service().create_from_candidate(
        owner_id=owner_id,
        instrument_id=symbol,
        idempotency_key=idempotency_key,
    )


async def _workflow_order_draft(owner_id: str, draft_id: str):
    if simulation_execution is None:
        _simulation_routes()
    if simulation_execution is None:
        raise RuntimeError("simulation execution service is unavailable")
    return await simulation_execution.get_draft(
        owner_id=owner_id,
        draft_id=draft_id,
    )


async def _workflow_order_draft_review(
    owner_id: str,
    draft_id: str,
    expected_revision: int,
):
    if simulation_execution is None:
        _simulation_routes()
    if simulation_execution is None:
        raise RuntimeError("simulation execution service is unavailable")
    command = {
        "draft_id": draft_id,
        "expected_revision": expected_revision,
    }
    return await simulation_execution.review(
        owner_id=owner_id,
        draft_id=draft_id,
        expected_revision=expected_revision,
        idempotency_key=stable_idempotency_key(
            "workflow-draft-review",
            {"owner_id": owner_id, **command},
        ),
        request_hash=canonical_request_hash(command),
    )


def _candidate_service() -> CandidateScoringService:
    """Build the deterministic candidate scoring service on demand."""
    portfolio = PortfolioQueryService(
        uow_factory=_simulation_uow_factory,
        clock=SystemClock(),
        rule_version=SIMULATION_RULE_VERSION,
    )
    return CandidateScoringService(
        portfolio=portfolio,
        quotes_provider=_candidate_quotes,
        rule_version=SIMULATION_RULE_VERSION,
    )


async def _workflow_candidates(
    owner_id: str,
    now,
    profile: dict | None,
) -> CandidateResponse:
    """Use the same candidate scorer and persisted ignore state as `/workspace`."""

    async with WorkspaceUnitOfWork(_workspace_session) as uow:
        ignores = await uow.candidate_ignores.list(owner_id)
    return await candidates_for_profile(
        service=_candidate_service(),
        owner_id=owner_id,
        now=now,
        profile=profile,
        ignored={row.instrument_id: row.reason for row in ignores},
    )


async def _trusted_simulation_market_reference(
    symbol: str,
) -> tuple[Decimal, VersionReference]:
    """Bind a draft to a server-read PandaData quote, never browser input."""

    requested_symbol = symbol.strip().upper()
    _service, application = _services()
    batch = await application.quotes((requested_symbol,))
    quote = next(
        (item for item in batch.quotes if item.symbol == requested_symbol),
        None,
    )
    if quote is None:
        message = (
            batch.errors.get(requested_symbol)
            or "trusted PandaData quote is unavailable"
        )
        raise ValueError(message)
    if quote.last <= 0:
        raise ValueError("trusted PandaData quote has no positive latest price")
    if quote.market_status not in {"in_session", "released"}:
        raise ValueError(
            f"trusted PandaData quote market status is {quote.market_status}"
        )
    if quote.freshness in {"error", "unavailable", "missing"}:
        raise ValueError(
            f"trusted PandaData quote freshness is {quote.freshness}"
        )
    return (
        quote.last,
        VersionReference(
            object_type="market_quote",
            object_id=quote.symbol,
            version=quote.provider_time,
        ),
    )


async def _trusted_historical_simulation_market_reference(
    owner_id: str,
    symbol: str,
) -> tuple[Decimal, VersionReference]:
    """Return the latest completed one-minute bar visible to the simulation clock."""

    simulation_clock = SimulationClockService(_workspace_session)
    clock = await simulation_clock.current_for_owner(owner_id)
    requested_symbol = symbol.strip().upper()
    trading_date = clock.current_time.astimezone(
        ZoneInfo("Asia/Shanghai")
    ).strftime("%Y%m%d")
    service, _application = _services()
    result = await asyncio.to_thread(
        service.read_historical_minute_bars,
        requested_symbol,
        trading_date=trading_date,
        limit=1_000,
    )
    completed = []
    for bar in result.bars:
        observed_at = datetime.fromisoformat(bar.provider_time)
        if (
            observed_at.tzinfo is not None
            and observed_at + timedelta(minutes=1) <= clock.current_time
        ):
            completed.append((observed_at, bar))
    if not completed:
        raise ValueError(
            "no completed PandaData minute bar is available at simulation time"
        )
    _observed_at, selected = max(completed, key=lambda item: item[0])
    if selected.close <= 0:
        raise ValueError("historical PandaData bar has no positive close")
    return (
        selected.close,
        VersionReference(
            object_type="simulation_historical_bar",
            object_id=requested_symbol,
            version=f"{selected.provider_time}:clock:{clock.revision}",
        ),
    )


async def _historical_simulation_market_bars(
    owner_id: str,
    symbol: str,
    frequency: str,
) -> dict[str, object]:
    clock = await SimulationClockService(_workspace_session).current_for_owner(owner_id)
    simulation_time = clock.current_time.astimezone(ZoneInfo("Asia/Shanghai"))
    service, _application = _services()
    if frequency == "daily":
        completed_date = simulation_time.date()
        if (simulation_time.hour, simulation_time.minute) < (15, 1):
            completed_date -= timedelta(days=1)
        result = await asyncio.to_thread(
            service.read_historical_daily_bars,
            symbol.strip().upper(),
            start_date=(completed_date - timedelta(days=1_500)).strftime("%Y%m%d"),
            end_date=completed_date.strftime("%Y%m%d"),
            limit=1_000,
        )
        visible = result.bars
    else:
        result = await asyncio.to_thread(
            service.read_historical_minute_bars,
            symbol.strip().upper(),
            trading_date=simulation_time.strftime("%Y%m%d"),
            limit=1_000,
        )
        visible = tuple(
            bar
            for bar in result.bars
            if (
                (observed_at := datetime.fromisoformat(bar.provider_time)).tzinfo
                is not None
                and observed_at + timedelta(minutes=1) <= clock.current_time
            )
        )
    if not visible:
        raise ValueError(
            f"no completed PandaData {frequency} bar is available at simulation time"
        )
    return {
        "bars": visible,
        "frequency": result.frequency,
        "simulation_time": clock.current_time,
        "simulation_clock_revision": clock.revision,
    }


async def _next_pandadata_session_open(after_close: datetime) -> datetime:
    local = after_close.astimezone(ZoneInfo("Asia/Shanghai"))
    if local.hour < 12:
        return local.replace(hour=13, minute=0, second=0, microsecond=0)
    cache_key = local.date().isoformat()
    cached = _simulation_next_session_cache.get(cache_key)
    if cached is not None:
        return cached
    service, _application = _services()
    candidate = local.date() + timedelta(days=1)
    for _ in range(20):
        result = await asyncio.to_thread(
            service.read_historical_minute_bars,
            "000001.SZ",
            trading_date=candidate.strftime("%Y%m%d"),
            limit=1,
        )
        if result.bars:
            resolved = datetime.combine(
                candidate,
                datetime.min.time().replace(hour=9, minute=30),
                ZoneInfo("Asia/Shanghai"),
            )
            _simulation_next_session_cache[cache_key] = resolved
            return resolved
        candidate += timedelta(days=1)
    raise ValueError("PandaData has no next A-share session within 20 days")


async def _validate_simulation_start(start_at: datetime) -> None:
    local = start_at.astimezone(ZoneInfo("Asia/Shanghai"))
    service, _application = _services()
    result = await asyncio.to_thread(
        service.read_historical_minute_bars,
        "000001.SZ",
        trading_date=local.strftime("%Y%m%d"),
        limit=1_000,
    )
    if not result.bars:
        raise ValueError(
            "simulation_start_at has no available PandaData one-minute data"
        )


def _trade_plan_service() -> TradePlanService:
    if simulation_execution is None:
        _simulation_routes()
    if simulation_execution is None:
        raise RuntimeError("simulation execution service is unavailable")
    clock = SystemClock()
    portfolio = PortfolioQueryService(
        uow_factory=_simulation_uow_factory,
        clock=clock,
        rule_version=SIMULATION_RULE_VERSION,
    )
    return TradePlanService(
        session_factory=_workspace_session,
        clock=clock,
        ids=UuidIdGenerator(),
        candidates=CandidateScoringService(
            portfolio=portfolio,
            quotes_provider=_candidate_quotes,
            rule_version=SIMULATION_RULE_VERSION,
        ),
        portfolio=portfolio,
        quotes_provider=_candidate_quotes,
        drafts=simulation_execution,
    )


def _evidence_service() -> EvidenceService:
    """Build the append-only evidence service on demand."""
    return EvidenceService(
        session_factory=_workspace_session,
        clock=SystemClock(),
        ids=UuidIdGenerator(),
    )


async def _record_agent_evidence(owner_id: str, subject: str, run) -> None:
    """Persist evidence for a completed direct Agent run before responding."""
    await _evidence_service().record_agent_run(
        owner_id=owner_id,
        run=run,
        subject=subject,
    )


async def _record_workflow_evidence(
    *,
    owner_id: str,
    subject: str,
    run,
    object_type: str,
    object_id: str,
    version: str,
    content: dict[str, object] | None = None,
    conclusion: str | None = None,
    provider: str = "multi-agent-runtime",
    generated_at=None,
) -> None:
    """Persist a real AgentRun or deterministic artifact before completion."""

    evidence = _evidence_service()
    if content is not None:
        await evidence.record(
            owner_id=owner_id,
            object_type=object_type,
            object_id=object_id,
            version=version,
            subject=subject,
            conclusion=conclusion,
            content=content,
            provider=provider,
            generated_at=generated_at,
        )
        return
    if run is None:
        raise ValueError("workflow evidence requires an AgentRun or content")
    await evidence.record_agent_run(
        owner_id=owner_id,
        run=run,
        subject=subject,
        object_type=object_type,
        object_id=object_id,
        version=version,
    )


async def _investor_profile_context(owner_id: str) -> dict | None:
    """Return a compact investor-profile context for the Multi-Agent runtime.

    Reads the caller's latest completed investment profile and selected/
    recommended directions so the planner and every prompt agent can tailor
    reasoning to the user's mandate. Returns ``None`` when no profile exists
    (for example a brand-new account) so the run proceeds without it.
    """
    async with create_db_session() as session:
        profile = await session.scalar(
            select(InvestmentProfile)
            .where(InvestmentProfile.user_id == owner_id)
            .order_by(InvestmentProfile.version.desc())
        )
        if profile is None:
            return None
        recommendations = (
            await session.scalars(
                select(DirectionRecommendation)
                .where(DirectionRecommendation.profile_id == profile.id)
                .order_by(DirectionRecommendation.rank)
            )
        ).all()
    selected = next((rec.direction for rec in recommendations if rec.selected), None)
    context: dict = {
        "version": profile.version,
        "archetype_code": profile.archetype_code,
        "archetype_title": profile.archetype_title,
        "risk_level": profile.risk_level,
        "loss_tolerance_percent": profile.loss_tolerance_percent,
        "confidence": profile.confidence,
        "completeness": profile.completeness,
        "education_only": profile.education_only,
        "objective_profile": profile.objective_profile,
        "dimension_scores": profile.dimension_scores,
        "recommended_directions": [rec.direction for rec in recommendations],
    }
    if selected is not None:
        context["selected_direction"] = selected
    return context


async def _workflow_profile_context(owner_id: str) -> dict | None:
    """Return only the approved suitability projection to workflow Agents."""

    raw = await _investor_profile_context(owner_id)
    if raw is None:
        return None
    projection = project_suitability_profile(raw)
    return projection.model_dump(mode="json") if projection.available else None


def _verified_knowledge_reader() -> VerifiedKnowledgeReader:
    global learning_context_reader
    if learning_context_reader is not None:
        return learning_context_reader
    with _learning_lock:
        if learning_context_reader is None:
            # Learning is an optional sidecar. Import its read-only consumer
            # only when an Agent request asks for learned context, never while
            # the trading API process starts or serves trading routes.
            from finance_god.learning.context import VerifiedKnowledgeReader
            from finance_god.learning.contracts import LearningConfig

            learning_context_reader = VerifiedKnowledgeReader(
                LearningConfig.from_environment().knowledge_dir
            )
    return learning_context_reader


async def _verified_learning_context(
    subject: str,
    task_type: str,
    asset_kind: str,
):
    query = f"{subject} {task_type} {asset_kind}"
    return await asyncio.to_thread(
        _verified_knowledge_reader().evidence,
        query=query,
        limit=6,
    )


class _WorkspaceNotificationSource:
    """Read unread notifications through the workspace unit of work."""

    async def list_unread(self, owner_id: str) -> list[Notification]:
        async with WorkspaceUnitOfWork(_workspace_session) as uow:
            return await uow.notifications.list_unread(owner_id)


def _assemble_simulation_routes() -> list:
    clock = SystemClock()
    simulation_clock = SimulationClockService(
        _workspace_session,
        next_session_resolver=_next_pandadata_session_open,
    )
    portfolio = PortfolioQueryService(
        uow_factory=_simulation_uow_factory,
        clock=clock,
        rule_version=SIMULATION_RULE_VERSION,
    )
    decision_inbox = DecisionInboxService(
        orders=simulation_execution,
        notifications=_WorkspaceNotificationSource(),
        clock=clock,
    )
    return create_simulation_routes(
        execution=simulation_execution,
        accounts=simulation_accounts,
        portfolio=portfolio,
        decision_inbox=decision_inbox,
        owner_resolver=_authenticated_owner,
        simulation_clock=simulation_clock,
        market_reference_provider=_trusted_simulation_market_reference,
        historical_market_reference_provider=(
            _trusted_historical_simulation_market_reference
        ),
        historical_market_bars_provider=_historical_simulation_market_bars,
        simulation_start_validator=_validate_simulation_start,
        trade_review_service=TradeReviewService(_workspace_session),
    )


def _simulation_routes() -> list:
    """Lazily build and cache simulation execution + account services."""
    global simulation_execution, simulation_accounts
    if simulation_execution is not None and simulation_accounts is not None:
        return _assemble_simulation_routes()
    try:
        clock = SystemClock()
        ids = UuidIdGenerator()

        class _StaticRuleCatalog:
            simulation_rule_version = SIMULATION_RULE_VERSION

        ledger = SimulationLedgerService(
            uow_factory=_simulation_uow_factory,
            clock=clock,
            ids=ids,
            rules=_StaticRuleCatalog(),
        )
        simulation_execution, simulation_accounts = build_simulation_services(
            uow_factory=_simulation_uow_factory,
            simulation_session_factory=_workspace_session,
            ledger=ledger,
            market_data=_services()[0],
            authorization=PersistentAuthorizationProvider(_mandate_service()),
            simulation_clock=SimulationClockService(
                _workspace_session,
                next_session_resolver=_next_pandadata_session_open,
            ),
        )
        _LOGGER.info("simulation services initialized successfully")
    except Exception:
        _LOGGER.exception("simulation service initialization failed")
        raise
    return _assemble_simulation_routes()


def _build_agent_runtime() -> MultiAgentRuntime:
    """Construct the Multi-Agent runtime, degrading gracefully on missing deps.

    FinRobot/FMP metrics are opt-in and never block startup. If PandaData is
    unavailable the runtime is rebuilt without the market-data provider so that
    evidence-only prompt agents still run; only a missing model endpoint makes
    the whole capability unavailable.
    """
    try:
        return MultiAgentRuntime.from_environment(
            enable_panda_data=True,
            enable_finrobot_metrics=False,
        )
    except Exception as first_error:  # noqa: BLE001 - retry without PandaData
        _LOGGER.warning(
            "agent runtime with PandaData failed (%s); retrying evidence-only",
            type(first_error).__name__,
        )
        return MultiAgentRuntime.from_environment(
            enable_panda_data=False,
            enable_finrobot_metrics=False,
        )


async def _agent_runtime_provider() -> MultiAgentRuntime:
    """Lazily build and cache the Multi-Agent runtime; report explicit failure."""
    global agent_runtime, agent_runtime_reason
    if agent_runtime is not None:
        return agent_runtime
    try:
        runtime = await asyncio.to_thread(_build_agent_runtime)
    except Exception as error:  # noqa: BLE001 - safe public unavailability boundary
        _LOGGER.error(
            "agent runtime initialization failed: %s",
            type(error).__name__,
        )
        agent_runtime_reason = "AI_RUNTIME_UNAVAILABLE"
        raise AgentRuntimeUnavailable(
            "The Multi-Agent runtime is not configured. Set the model endpoint "
            "environment variables to enable AI research."
        ) from error
    with _agent_lock:
        if agent_runtime is None:
            agent_runtime = runtime
            agent_runtime_reason = None
    return agent_runtime


async def _generate_desk_quick_commands(
    _owner_id: str,
    stage: str,
    section: str,
    symbol: str,
    instrument_name: str,
    projection,
    answer_text: str | None,
    workflow_evidence: dict | None,
) -> tuple[str, str, str]:
    runtime = await _agent_runtime_provider()
    return await runtime.generate_desk_quick_commands(
        stage=stage,
        section=section,
        symbol=symbol,
        instrument_name=instrument_name,
        profile_projection=projection.model_dump(mode="json"),
        answer_text=answer_text,
        workflow_evidence=workflow_evidence,
    )


async def _record_desk_decision(
    owner_id: str,
    decision_id: str,
    answer_text: str,
) -> None:
    now = monotonic()
    expired = [
        key
        for key, (_, _, created_at) in _desk_decision_contexts.items()
        if now - created_at > _DESK_DECISION_CONTEXT_TTL_SECONDS
    ]
    for key in expired:
        _desk_decision_contexts.pop(key, None)
    if len(_desk_decision_contexts) >= 512:
        oldest = min(
            _desk_decision_contexts,
            key=lambda key: _desk_decision_contexts[key][2],
        )
        _desk_decision_contexts.pop(oldest, None)
    _desk_decision_contexts[decision_id] = (owner_id, answer_text, now)


async def _desk_quick_command_context(
    owner_id: str,
    stage: str,
    reference: str,
) -> str | dict:
    if stage == "after_answer":
        stored = _desk_decision_contexts.get(reference)
        if stored is None or stored[0] != owner_id:
            raise LookupError("direct-answer context is unavailable")
        if monotonic() - stored[2] > _DESK_DECISION_CONTEXT_TTL_SECONDS:
            _desk_decision_contexts.pop(reference, None)
            raise LookupError("direct-answer context has expired")
        return stored[1]
    commands = _workflow_command_provider()
    if await commands.get_owner_id(reference) != owner_id:
        raise LookupError("workflow is unavailable")
    run = await commands.get(reference)
    if (
        run is None
        or run.status.value != "completed"
        or run.final_artifact is None
    ):
        raise ValueError("workflow has not produced final evidence")
    evidence = await _evidence_service().get(
        owner_id=owner_id,
        object_type=run.final_artifact.object_type,
        object_id=run.final_artifact.object_id,
        version=run.final_artifact.version,
    )
    return evidence.model_dump(mode="json", exclude={"error_trace"})


def _desk_instrument_name(symbol: str) -> str:
    instrument = _services()[0].resolve(symbol)
    return instrument.name or instrument.symbol


finance_routes = [
    Route("/live", live),
    Route("/ready", ready),
    Route("/health", health),
    Route("/market/quotes", quotes),
    Route("/market/overview", market_overview),
    Route("/market/bars", bars),
    Route("/market/information-facts", information_facts),
    Route("/market/sentiment-facts", sentiment_facts),
    Route("/market/instruments", instruments),
    Route("/market/catalog", catalog),
    Route("/market/snapshots", snapshots),
    Route("/market/alerts", alerts),
    Mount(
        "/workspace",
        routes=create_workspace_routes(
            session_factory=_workspace_session,
            owner_resolver=_authenticated_owner,
            candidate_service_provider=_candidate_service,
            candidate_profile_provider=_workflow_profile_context,
        ),
        name="workspace",
    ),
    Mount(
        "/simulation",
        routes=_simulation_routes(),
        name="simulation",
    ),
    Mount(
        "/trade-episodes",
        routes=create_trade_episode_routes(
            service=TradeReviewService(_workspace_session),
            owner_resolver=_authenticated_owner,
        ),
        name="trade-episodes",
    ),
    Mount(
        "/trade-plans",
        routes=create_trade_plan_routes(
            service_provider=_trade_plan_service,
            owner_resolver=_authenticated_owner,
        ),
        name="trade-plans",
    ),
    Mount(
        "/mandate",
        routes=create_mandate_routes(
            session_factory=_workspace_session,
            owner_resolver=_authenticated_owner,
            clock=SystemClock(),
            ids=UuidIdGenerator(),
            orders_provider=lambda: simulation_execution,
        ),
        name="mandate",
    ),
    Mount(
        "/evidence",
        routes=create_evidence_routes(
            service_provider=_evidence_service,
            owner_resolver=_authenticated_owner,
        ),
        name="evidence",
    ),
    *create_workflow_routes(
        commands_provider=_workflow_command_provider,
        definition_provider=_workflow_definition,
        owner_resolver=_authenticated_owner,
        instrument_validator=lambda symbol: _services()[0].resolve(symbol),
        work_available=lambda: (
            workflow_worker_wakeup.set()
            if workflow_worker_wakeup is not None
            else None
        ),
    ),
    *create_desk_routes(
        owner_resolver=_authenticated_owner,
        profile_provider=_investor_profile_context,
        workflow_worker_enabled=settings.workflow_worker_enabled,
        capability_provider=_desk_capability_probe,
        quick_command_provider=_generate_desk_quick_commands,
        quick_command_context_provider=_desk_quick_command_context,
        instrument_name_provider=_desk_instrument_name,
        market_focus_recorder=_record_market_focus,
    ),
    *create_event_routes(
        session_factory=_workspace_session,
        owner_resolver=_authenticated_owner,
    ),
    Mount(
        "/agent",
        routes=create_agent_routes(
            runtime_provider=_agent_runtime_provider,
            owner_resolver=_authenticated_owner,
            evidence_recorder=_record_agent_evidence,
            profile_provider=_investor_profile_context,
            portfolio_provider=_workflow_portfolio,
            learning_context_provider=_verified_learning_context,
            workflow_definition_provider=_workflow_definition,
            decision_recorder=_record_desk_decision,
        ),
        name="agent",
    ),
    Mount(
        "/agent-learning",
        routes=create_agent_learning_routes(
            owner_resolver=_authenticated_owner,
            reader_provider=AgentLearningSummaryReader.from_environment,
        ),
        name="agent-learning",
    ),
    *create_crawler_routes(),
]

finance_app = Starlette(debug=False, routes=finance_routes)
