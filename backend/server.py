"""Finance API composition mounted exclusively by ``app.main:app``."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC
from decimal import Decimal
from threading import Lock
from typing import TYPE_CHECKING
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from app.config import settings
from app.core.security import resolve_active_user
from app.db.session import create_db_session
from app.models.profile import DirectionRecommendation, InvestmentProfile
from finance_god.api.agent_routes import (
    AgentRuntimeUnavailable,
    create_agent_routes,
)
from finance_god.api.auth import AuthenticationError
from finance_god.api.crawler_routes import create_crawler_routes
from finance_god.api.evidence_routes import create_evidence_routes
from finance_god.api.mandate_routes import create_mandate_routes
from finance_god.api.simulation import create_simulation_routes
from finance_god.api.trade_plan_routes import create_trade_plan_routes
from finance_god.api.workflow_routes import (
    WorkflowRuntimeUnavailable,
    create_workflow_routes,
)
from finance_god.api.workspace_routes import create_workspace_routes
from finance_god.application.candidate_service import CandidateScoringService
from finance_god.application.decision_inbox import DecisionInboxService
from finance_god.application.evidence_service import EvidenceService
from finance_god.application.ledger_service import SimulationLedgerService
from finance_god.application.mandate_service import MandateService
from finance_god.application.market_overview import build_market_overview
from finance_god.application.market_poller import MarketPoller
from finance_god.application.portfolio_query import PortfolioQueryService
from finance_god.application.trade_plan_service import TradePlanService
from finance_god.domain import Notification
from finance_god.domain.simulation_rules import SIMULATION_RULE_VERSION
from finance_god.infrastructure.mandate_provider import (
    PersistentAuthorizationProvider,
)
from finance_god.infrastructure.persistence.market_monitor_repository import (
    MarketMonitorUnitOfWork,
)
from finance_god.infrastructure.persistence.uow import SqlAlchemyUnitOfWork
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
    capability_catalog_summary,
)
from finance_god.orchestration.multi_agent import MultiAgentRuntime
from finance_god.orchestration.workflows import (
    WorkflowCommandPort,
    WorkflowCommandRuntime,
    WorkflowCreateCommand,
    WorkflowKey,
    create_workflow_command_runtime_from_environment,
)

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
_agent_lock = Lock()
_learning_lock = Lock()
_service_lock = Lock()
_crawler_service: "CrawlerService | None" = None


def _crawler_service_instance() -> "CrawlerService":
    """Lazily create the shared CrawlerService singleton."""
    global _crawler_service
    if _crawler_service is None:
        from finance_god.crawler.service import CrawlerService
        _crawler_service = CrawlerService()
    return _crawler_service


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
    try:
        yield
    finally:
        runtime = workflow_runtime
        stop_event = market_poller_stop
        poller_task = market_poller_task
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
        if stop_event is not None:
            stop_event.set()
        if poller_task is not None:
            try:
                await poller_task
            except Exception:  # noqa: BLE001 - shutdown must not raise
                _LOGGER.warning("market poller task did not shut down cleanly")
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


async def market_overview(request: Request) -> JSONResponse:
    symbols = request.query_params.get("symbols", "").split(",")
    try:
        _, application = _services()
        batch = await application.quotes(symbols)
        if not batch.quotes:
            return _safe_error(
                code="MARKET_DATA_EMPTY_RESPONSE",
                message="No market data is available for the overview.",
                status_code=502,
            )
        result = build_market_overview(batch)
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
    return _json(result)


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


async def information_facts(request: Request) -> JSONResponse:
    """Return market news/research sourced from the crawler (eastmoney).

    Replaces PandaData financial-report disclosures with real-time industry
    news and broker research reports crawled from public sources.
    """
    symbol = request.query_params.get("symbol", "")
    limit = min(int(request.query_params.get("limit", "10")), 30)

    # Map stock symbol to a sector hint for the crawler
    sector = request.query_params.get("sector", "")

    try:
        news = await _crawler_service_instance().get_news(
            sector=sector, limit=limit
        )
        facts = [
            {
                "scope": f"news:{item.sector or 'general'}",
                "fields": [
                    {"name": "title", "value": item.title},
                    {"name": "summary", "value": item.summary},
                    {"name": "source", "value": item.source},
                    {"name": "url", "value": item.url},
                    {"name": "sector", "value": item.sector},
                ],
            }
            for item in news
        ]
        return _json({
            "provider": "Finance-God/Crawler",
            "fact_kind": "industry_news",
            "symbol": symbol.upper() if symbol else "A_SHARE_MARKET",
            "requested_at": news[0].publish_time.isoformat() if news and news[0].publish_time else None,
            "facts": facts,
            "news": [item.model_dump(mode="json") for item in news],
            "trade_eligible": False,
        })
    except Exception:  # noqa: BLE001 - public HTTP error boundary
        return _internal_error()


async def sentiment_facts(request: Request) -> JSONResponse:
    """Return market sentiment sourced from the crawler (eastmoney+ths).

    Replaces PandaData margin-balance facts with richer multi-dimensional
    sentiment data: score, level, breadth, north_flow, sector_flows.
    """
    from finance_god.crawler.service import CrawlerService

    try:
        sentiment = await _crawler_service_instance().get_sentiment()
        data = sentiment.model_dump(mode="json")
        return _json({
            "provider": "Finance-God/Crawler",
            "fact_kind": "market_sentiment",
            "symbol": request.query_params.get("symbol", "A_SHARE_MARKET"),
            "requested_at": data["retrieved_at"],
            "sentiment": data,
            "facts": [
                {
                    "scope": "market_sentiment_score",
                    "fields": [
                        {"name": "score", "value": sentiment.score},
                        {"name": "level", "value": sentiment.level.value},
                        {"name": "north_flow", "value": sentiment.north_flow},
                        {"name": "up_ratio", "value": sentiment.breadth.up_ratio},
                        {"name": "limit_up", "value": sentiment.breadth.limit_up},
                        {"name": "limit_down", "value": sentiment.breadth.limit_down},
                    ],
                },
            ],
            "trade_eligible": False,
        })
    except Exception:  # noqa: BLE001 - public HTTP error boundary
        return _internal_error()


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


async def _candidate_quotes(symbols: list[str]):
    _, application = _services()
    return await application.quotes(symbols)


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
        _LOGGER.error(
            "market poll universe derivation failed: %s",
            type(error).__name__,
        )
        return None, None
    if not universe:
        _LOGGER.info("market poller idle: no priceable instruments in universe")
        return None, None
    escalate = settings.market_alert_escalate_threshold
    poller = MarketPoller(
        quotes_provider=_candidate_quotes,
        uow_factory=_market_monitor_uow,
        threshold=Decimal(str(settings.market_alert_threshold)),
        escalate_threshold=(
            Decimal(str(escalate)) if escalate is not None else None
        ),
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
    """Persist evidence for a completed agent run (best-effort, non-blocking)."""
    await _evidence_service().record_agent_run(
        owner_id=owner_id,
        run=run,
        subject=subject,
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
            authorization=PersistentAuthorizationProvider(_mandate_service()),
        )
        _LOGGER.info("simulation services initialized successfully")
    except Exception as error:  # noqa: BLE001
        _LOGGER.error(
            "simulation service initialization failed: %s: %s",
            type(error).__name__,
            error,
        )
        return []
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
        ),
        name="workspace",
    ),
    Mount(
        "/simulation",
        routes=_simulation_routes(),
        name="simulation",
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
    ),
    Mount(
        "/agent",
        routes=create_agent_routes(
            runtime_provider=_agent_runtime_provider,
            owner_resolver=_authenticated_owner,
            evidence_recorder=_record_agent_evidence,
            profile_provider=_investor_profile_context,
            learning_context_provider=_verified_learning_context,
        ),
        name="agent",
    ),
    *create_crawler_routes(),
]

finance_app = Starlette(debug=False, routes=finance_routes)
