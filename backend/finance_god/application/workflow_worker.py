"""Workflow Worker backed by the real unified Multi-Agent runtime.

The worker never marks a research workflow completed from placeholder artifacts:
Agent nodes must return a real ``AgentRun`` and the finalizer must persist its
evidence bundle before the WorkflowRun can enter ``completed``. Deterministic
services without a production adapter fail explicitly.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final, Protocol

from research_runtime import (
    AgentPlan,
    AgentRequest,
    AgentRun,
    AssetKind,
    ExecutionProfile,
)
from research_runtime.contracts import AgentAssignment, RoutingNotice
from research_runtime.models import EvidenceRecord

from finance_god.agents.catalog import PLANNER_ID, AgentGovernanceCatalog
from finance_god.agents.contracts import FailureKind, WorkflowKey
from finance_god.agents.language_policy import natural_chinese_requirement
from finance_god.application.candidate_service import (
    CandidateResponse,
    candidate_response_conclusion,
    evidence_content_from_candidate_response,
)
from finance_god.application.portfolio_query import PortfolioView
from finance_god.application.trade_plan_service import TradePlanPageView
from finance_god.crawler.models import CrawlerResult
from finance_god.domain import ConcurrentCommandConflict
from finance_god.domain.models import (
    AuditReference,
    VersionReference,
    WorkflowCancellationReason,
    WorkflowRun,
    WorkflowRunStatus,
)
from finance_god.execution import StoredDraft
from finance_god.infrastructure.simulation_wiring import SystemClock
from finance_god.market_data.monitor import MarketAlert, MarketSnapshot
from finance_god.market_data.service import (
    MarketBarsResult,
    MarketFactBatch,
    MarketQuote,
    QuoteBatch,
)
from finance_god.orchestration.task_plans import TaskPlanFactory
from finance_god.orchestration.workflow_commands import WorkflowRunRepository
from finance_god.orchestration.workflow_executor import (
    NodeExecutionContext,
    NodeExecutionError,
    NodeExecutionOutcome,
    WorkflowControlState,
    WorkflowExecutionReport,
    WorkflowExecutor,
)
from finance_god.orchestration.workflow_registry import (
    FormalWorkflowRegistry,
    WorkflowDefinition,
    WorkflowNodeDefinition,
)
from finance_god.orchestration.workflow_results import OrderRiskCheckNodeResult

_LOGGER = logging.getLogger(__name__)
_PLAN_ID_SAFE = re.compile(r"[^A-Za-z0-9_-]+")
_ACTIVE_WORKFLOW_PROFILES = frozenset(
    {ExecutionProfile.RESEARCH, ExecutionProfile.WORKSPACE}
)
_MARKET_REGIME_INDEX: Final = "000300.SH"
_OPTION_VOLATILITY_UNDERLYING: Final = "510300.SH"
_MIN_MARKET_CONTEXT_DAILY_BARS: Final = 10


class Clock(Protocol):
    def now(self): ...


class AgentRuntime(Protocol):
    async def run(self, request: AgentRequest) -> AgentRun: ...

    def list_agents(self) -> tuple: ...

    @property
    def available_resources(self) -> frozenset[str]: ...


class WorkflowEvidenceRecorder(Protocol):
    async def __call__(
        self,
        *,
        owner_id: str,
        subject: str,
        run: AgentRun | None,
        object_type: str,
        object_id: str,
        version: str,
        content: dict[str, object] | None = None,
        conclusion: str | None = None,
        provider: str = "multi-agent-runtime",
        generated_at: datetime | None = None,
    ) -> None: ...


ProfileProvider = Callable[[str], Awaitable[dict | None]]
RuntimeProvider = Callable[[], Awaitable[AgentRuntime]]
CandidateProvider = Callable[
    [str, datetime, dict | None],
    Awaitable[CandidateResponse],
]
MarketContextProvider = Callable[[list[str]], Awaitable[QuoteBatch]]
MarketHistoryProvider = Callable[..., Awaitable[MarketBarsResult]]
MarketFactsProvider = Callable[..., Awaitable[MarketFactBatch]]
CrawlerContextProvider = Callable[[], Awaitable[CrawlerResult]]
PortfolioProvider = Callable[[str], Awaitable[PortfolioView]]
TradePlanProvider = Callable[[str, str, str], Awaitable[TradePlanPageView]]
OrderDraftProvider = Callable[[str, str], Awaitable[StoredDraft]]
OrderDraftReviewProvider = Callable[[str, str, int], Awaitable[StoredDraft]]


@dataclass(frozen=True)
class MarketAlertContext:
    snapshot: MarketSnapshot | None
    latest_alert: MarketAlert | None
    observed_at: datetime


MarketAlertContextProvider = Callable[[str], Awaitable[MarketAlertContext]]


class WorkflowWorkerUnitOfWork(Protocol):
    workflows: WorkflowRunRepository

    async def commit(self) -> None: ...


UowFactory = Callable[[], AbstractAsyncContextManager[WorkflowWorkerUnitOfWork]]


class CommittedWorkflowRepository:
    """Persist every executor mutation in its own short transaction.

    Agent work may take minutes. Keeping the WorkflowRun transaction open for
    that duration hides progress from readers and lets a second Worker block on
    the same row. Per-operation commits make the initial QUEUED -> RUNNING CAS
    the claim boundary and expose every subsequent node revision immediately.
    """

    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory

    async def get(self, run_id: str) -> WorkflowRun | None:
        async with self._uow_factory() as uow:
            return await uow.workflows.get(run_id)

    async def get_owner_id(self, run_id: str) -> str | None:
        async with self._uow_factory() as uow:
            return await uow.workflows.get_owner_id(run_id)

    async def get_record(self, run_id: str) -> dict[str, object] | None:
        async with self._uow_factory() as uow:
            return await uow.workflows.get_record(run_id)

    async def list_execution_audits(self, run_id: str) -> tuple:
        async with self._uow_factory() as uow:
            return await uow.workflows.list_execution_audits(run_id)

    async def compare_and_append(
        self,
        *,
        run: WorkflowRun,
        expected_revision: int,
        event_type: str,
        event_payload: dict[str, object],
        outbox_topic: str,
    ) -> WorkflowRun:
        async with self._uow_factory() as uow:
            stored = await uow.workflows.compare_and_append(
                run=run,
                expected_revision=expected_revision,
                event_type=event_type,
                event_payload=event_payload,
                outbox_topic=outbox_topic,
            )
            await uow.commit()
            return stored

    async def append_audit(
        self,
        *,
        audit_id: str,
        run_id: str,
        event_type: str,
        payload_json: dict[str, object],
        occurred_at: datetime,
        actor_id: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        async with self._uow_factory() as uow:
            await uow.workflows.append_audit(
                audit_id=audit_id,
                run_id=run_id,
                event_type=event_type,
                payload_json=payload_json,
                occurred_at=occurred_at,
                actor_id=actor_id,
                correlation_id=correlation_id,
            )
            await uow.commit()


class OpenControls:
    """Default production control port: never pause or hard-block."""

    def current(self, run_id: str) -> WorkflowControlState:
        del run_id
        return WorkflowControlState()


CONNECTED_DETERMINISTIC_SERVICES = frozenset(
    {
        "workflow.input_quality_gate",
        "workflow.artifact_finalize",
        "candidate.score",
        "market_context.snapshot",
        "crawler.context",
        "market_alert_context.resolve",
        "portfolio.stress_calculate",
        "trade_plan.calculate",
        "order_review.calculate",
        "risk.pre_submit",
        "strategy.monitor_compare",
    }
)


def worker_supports(definition: WorkflowDefinition) -> bool:
    """Return whether this Worker can execute every deterministic node."""

    return all(
        node.service_id is None or node.service_id in CONNECTED_DETERMINISTIC_SERVICES
        for node in definition.nodes
    )


class RealWorkflowNodeRunner:
    """Execute governed Agent nodes and persist their real, readable output."""

    def __init__(
        self,
        *,
        runtime_provider: RuntimeProvider,
        evidence_recorder: WorkflowEvidenceRecorder,
        request_intent: str,
        profile_provider: ProfileProvider | None = None,
        candidate_provider: CandidateProvider | None = None,
        market_context_provider: MarketContextProvider | None = None,
        market_history_provider: MarketHistoryProvider | None = None,
        information_facts_provider: MarketFactsProvider | None = None,
        sentiment_facts_provider: MarketFactsProvider | None = None,
        crawler_context_provider: CrawlerContextProvider | None = None,
        market_alert_context_provider: MarketAlertContextProvider | None = None,
        portfolio_provider: PortfolioProvider | None = None,
        trade_plan_provider: TradePlanProvider | None = None,
        order_draft_provider: OrderDraftProvider | None = None,
        order_draft_review_provider: OrderDraftReviewProvider | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._runtime_provider = runtime_provider
        self._evidence_recorder = evidence_recorder
        self._request_intent = request_intent.strip()
        self._profile_provider = profile_provider
        self._candidate_provider = candidate_provider
        self._market_context_provider = market_context_provider
        self._market_history_provider = market_history_provider
        self._information_facts_provider = information_facts_provider
        self._sentiment_facts_provider = sentiment_facts_provider
        self._crawler_context_provider = crawler_context_provider
        self._market_alert_context_provider = market_alert_context_provider
        self._portfolio_provider = portfolio_provider
        self._trade_plan_provider = trade_plan_provider
        self._order_draft_provider = order_draft_provider
        self._order_draft_review_provider = order_draft_review_provider
        self._clock = clock or SystemClock()
        self._agent_runs: dict[str, AgentRun] = {}
        self._candidate_response: CandidateResponse | None = None
        self._service_evidence: dict[str, list[EvidenceRecord]] = {}
        self._attempts: dict[str, int] = {}
        self._market_observed_at: datetime | None = None
        self._order_draft: StoredDraft | None = None
        self._portfolio_focus_symbol: str | None = None

    async def run(
        self,
        node: WorkflowNodeDefinition,
        context: NodeExecutionContext,
    ) -> NodeExecutionOutcome:
        attempt = self._attempts.get(node.node_id, 0) + 1
        self._attempts[node.node_id] = attempt
        if node.agent_ids:
            return await self._run_agent_node(node, context, attempt)
        return await self._run_service_node(node, context, attempt)

    def _service_evidence_records(self) -> list[EvidenceRecord]:
        return [
            evidence
            for node_id in sorted(self._service_evidence)
            for evidence in self._service_evidence[node_id]
        ]

    async def _run_agent_node(
        self,
        node: WorkflowNodeDefinition,
        context: NodeExecutionContext,
        attempt: int,
    ) -> NodeExecutionOutcome:
        if node.agent_ids == (PLANNER_ID,):
            return NodeExecutionOutcome(
                node_id=node.node_id,
                artifact_reference=VersionReference(
                    object_type="TaskPlan",
                    object_id=context.plan_reference.object_id,
                    version=context.plan_reference.version,
                ),
                permissions_used=tuple(sorted(node.tool_allowlist)),
            )

        try:
            runtime = await self._runtime_provider()
            definitions = {item.agent_id: item for item in runtime.list_agents()}
            missing = sorted(set(node.agent_ids) - set(definitions))
            if missing:
                raise ValueError(
                    f"runtime catalog is missing governed agents: {missing}"
                )
            profile = (
                await self._profile_provider(context.owner_id)
                if self._profile_provider is not None
                else None
            )
            combined_run_id = _agent_run_id(context.run_id, node.node_id, attempt)
            evidence = _dedupe_evidence(
                [
                    *self._service_evidence_records(),
                    *_input_evidence(context),
                    *_prior_agent_evidence(self._agent_runs),
                ]
            )
            assignments: list[AgentAssignment] = []
            notices: list[RoutingNotice] = []
            results = []
            for index, agent_id in enumerate(node.agent_ids, start=1):
                definition = definitions[agent_id]
                if definition.minimum_profile not in _ACTIVE_WORKFLOW_PROFILES:
                    raise PermissionError(
                        f"{agent_id} requires unavailable "
                        f"{definition.minimum_profile.value} execution profile"
                    )
                requested_resources = frozenset(definition.required_resources)
                missing_resources = sorted(
                    requested_resources - runtime.available_resources
                )
                if missing_resources:
                    raise PermissionError(
                        f"{agent_id} requires unavailable resources: "
                        f"{', '.join(missing_resources)}"
                    )
                agent_payload = _agent_payload(
                    agent_id,
                    context,
                    self._market_observed_at or self._clock.now(),
                )
                if (
                    agent_id == "quantskills:agent-crowding-risk-monitor"
                    and not agent_payload.get("symbol")
                    and self._portfolio_focus_symbol is not None
                ):
                    agent_payload = {
                        **agent_payload,
                        "symbol": self._portfolio_focus_symbol,
                    }
                request = AgentRequest(
                    run_id=f"{combined_run_id}-{index}"[:96],
                    subject=self._request_intent,
                    task_type=_task_type(definition.task_types),
                    profile=definition.minimum_profile,
                    asset_kind=_asset_kind(context.input_versions),
                    available_resources=set(runtime.available_resources),
                    requested_agent_ids=[agent_id],
                    evidence=evidence,
                    payload={
                        "workflow_key": context.workflow_key.value,
                        "workflow_version": context.workflow_version,
                        **({"investor_profile": profile} if profile else {}),
                        **agent_payload,
                    },
                    max_agents=1,
                )
                _LOGGER.info(
                    "workflow agent started run=%s node=%s agent=%s attempt=%d",
                    context.run_id,
                    node.node_id,
                    agent_id,
                    attempt,
                )
                agent_run = await runtime.run(request)
                _LOGGER.info(
                    "workflow agent completed run=%s node=%s agent=%s agent_run=%s",
                    context.run_id,
                    node.node_id,
                    agent_id,
                    agent_run.run_id,
                )
                result = agent_run.results[0]
                result = result.model_copy(
                    update={"evidence": _dedupe_evidence([*evidence, *result.evidence])}
                )
                assignments.extend(agent_run.plan.assignments)
                notices.extend(agent_run.plan.notices)
                results.append(result)
                evidence = _extend_evidence(evidence, result, index)
            combined = AgentRun(
                run_id=combined_run_id,
                plan=AgentPlan(
                    run_id=combined_run_id,
                    assignments=assignments,
                    notices=notices,
                ),
                results=results,
            )
        except PermissionError as error:
            raise NodeExecutionError(FailureKind.PERMISSION, str(error)) from error
        except ValueError as error:
            raise NodeExecutionError(FailureKind.VALIDATION, str(error)) from error
        except NodeExecutionError:
            raise
        except Exception as error:  # noqa: BLE001 - runtime boundary
            _LOGGER.exception(
                "workflow agent failed run=%s node=%s agents=%s attempt=%d",
                context.run_id,
                node.node_id,
                ",".join(node.agent_ids),
                attempt,
            )
            raise NodeExecutionError(
                FailureKind.TRANSIENT,
                (
                    f"multi-agent runtime failed: {type(error).__name__}: "
                    f"{str(error)[:500]}"
                ),
            ) from error

        self._agent_runs[node.node_id] = combined
        evidence_references = tuple(
            VersionReference(
                object_type="Evidence",
                object_id=f"{context.run_id}:{item.identifier}"[:160],
                version=combined.run_id,
            )
            for item in evidence
        )
        contribution_references = tuple(
            VersionReference(
                object_type="AgentContribution",
                object_id=f"{context.run_id}:{result.agent_id}"[:160],
                version=combined.run_id,
            )
            for result in combined.results
        )
        pending_actions = tuple(
            sorted(
                {
                    action
                    for result in combined.results
                    for action in result.proposed_actions
                }
            )
        )
        return NodeExecutionOutcome(
            node_id=node.node_id,
            artifact_reference=VersionReference(
                object_type="AgentResearchBundle",
                object_id=f"{context.run_id}:{node.node_id}"[:160],
                version=combined.run_id,
            ),
            evidence_references=evidence_references,
            contribution_references=contribution_references,
            permissions_used=tuple(sorted(node.tool_allowlist)),
            pending_actions=pending_actions,
        )

    async def _run_service_node(
        self,
        node: WorkflowNodeDefinition,
        context: NodeExecutionContext,
        attempt: int,
    ) -> NodeExecutionOutcome:
        if node.service_id == "workflow.input_quality_gate":
            usable = bool(context.input_versions) and all(
                item.object_type.strip()
                and item.object_id.strip()
                and item.version.strip()
                for item in context.input_versions
            )
            return NodeExecutionOutcome(
                node_id=node.node_id,
                artifact_reference=VersionReference(
                    object_type="InputQualityDecision",
                    object_id=f"{context.run_id}:input-quality",
                    version=f"attempt-{attempt}",
                ),
                permissions_used=tuple(sorted(node.tool_allowlist)),
                quality_gate_passed=usable,
            )
        if node.service_id == "candidate.score":
            if self._candidate_provider is None:
                raise NodeExecutionError(
                    FailureKind.VALIDATION,
                    "deterministic service is not connected: candidate.score",
                )
            try:
                profile = (
                    await self._profile_provider(context.owner_id)
                    if self._profile_provider is not None
                    else None
                )
                response = await self._candidate_provider(
                    context.owner_id,
                    self._clock.now(),
                    profile,
                )
            except Exception as error:  # noqa: BLE001 - application service boundary
                raise NodeExecutionError(
                    FailureKind.TRANSIENT,
                    f"candidate scoring failed: {type(error).__name__}",
                ) from error
            self._candidate_response = response
            return NodeExecutionOutcome(
                node_id=node.node_id,
                artifact_reference=VersionReference(
                    object_type="CandidateScoringResult",
                    object_id=context.run_id,
                    version=response.generated_at.isoformat(),
                ),
                permissions_used=tuple(sorted(node.tool_allowlist)),
                quality_gate_passed=response.unavailable_reason is None,
            )
        if node.service_id == "market_context.snapshot":
            if self._market_context_provider is None:
                raise NodeExecutionError(
                    FailureKind.VALIDATION,
                    "deterministic service is not connected: market_context.snapshot",
                )
            symbol = _instrument_symbol(context.input_versions)
            if not symbol:
                raise NodeExecutionError(
                    FailureKind.VALIDATION,
                    "market context requires an instrument_context input",
                )
            if attempt > 1:
                # The PandaData adapter and shared singleflight cache can be
                # briefly busy while the page refreshes the same symbol. A
                # governed retry must yield before trying the identical call
                # again; three immediate attempts only repeat the same race.
                await asyncio.sleep(0.25 * (2 ** (attempt - 2)))
            try:
                batch = await self._market_context_provider([symbol])
            except Exception as error:  # noqa: BLE001 - market-data boundary
                _LOGGER.exception(
                    "market context snapshot failed run=%s node=%s symbol=%s "
                    "attempt=%d",
                    context.run_id,
                    node.node_id,
                    symbol,
                    attempt,
                )
                raise NodeExecutionError(
                    FailureKind.TRANSIENT,
                    (
                        f"market context snapshot failed: {type(error).__name__}: "
                        f"{str(error)[:300]}"
                    ),
                ) from error
            quote = next(
                (item for item in batch.quotes if item.symbol == symbol),
                None,
            )
            if quote is None:
                reason = batch.errors.get(symbol, "quote unavailable")
                raise NodeExecutionError(
                    FailureKind.VALIDATION,
                    f"market context snapshot unavailable: {reason}",
                )
            evidence = EvidenceRecord(
                identifier=f"market-context-{symbol}",
                source=f"{quote.provider}:{symbol}",
                excerpt=(
                    f"last={quote.last}; change_percent={quote.change_percent}; "
                    f"provider_time={quote.provider_time}; "
                    f"frequency={quote.frequency}; freshness={quote.freshness}; "
                    f"session_alignment={quote.session_alignment}; "
                    f"market_status={quote.market_status}"
                ),
            )
            self._market_observed_at = _provider_datetime(quote.provider_time)
            end_date = self._market_observed_at.strftime("%Y%m%d")
            start_date = (self._market_observed_at - timedelta(days=30)).strftime(
                "%Y%m%d"
            )
            if self._market_history_provider is None:
                raise NodeExecutionError(
                    FailureKind.VALIDATION,
                    "deterministic service is not connected: target market history",
                )
            try:
                history = await self._market_history_provider(
                    symbol,
                    start_date=start_date,
                    end_date=end_date,
                    limit=1_000,
                )
            except Exception as error:  # noqa: BLE001 - market-data boundary
                raise NodeExecutionError(
                    FailureKind.TRANSIENT,
                    (
                        "target market history failed: "
                        f"{type(error).__name__}: {str(error)[:300]}"
                    ),
                ) from error
            if len(history.bars) < _MIN_MARKET_CONTEXT_DAILY_BARS:
                raise NodeExecutionError(
                    FailureKind.VALIDATION,
                    (
                        f"target market history is insufficient for {symbol}: "
                        f"expected at least {_MIN_MARKET_CONTEXT_DAILY_BARS} "
                        f"daily bars in {start_date}-{end_date}, "
                        f"received {len(history.bars)}"
                    ),
                )
            history_evidence = _market_history_evidence(
                symbol,
                start_date,
                end_date,
                history,
            )
            fact_evidence: list[EvidenceRecord] = []
            if getattr(quote, "asset_type", "equity") == "equity":
                if (
                    self._information_facts_provider is None
                    or self._sentiment_facts_provider is None
                ):
                    raise NodeExecutionError(
                        FailureKind.VALIDATION,
                        "deterministic service is not connected: instrument research facts",
                    )
                start_quarter, end_quarter = _research_quarter_range(
                    self._market_observed_at
                )
                try:
                    information = await self._information_facts_provider(
                        symbol,
                        start_quarter=start_quarter,
                        end_quarter=end_quarter,
                        limit=12,
                    )
                except Exception as error:  # noqa: BLE001 - market-data boundary
                    raise NodeExecutionError(
                        FailureKind.TRANSIENT,
                        f"company disclosure facts failed: {type(error).__name__}: "
                        f"{str(error)[:300]}",
                    ) from error
                fact_evidence.extend(_market_fact_evidence(information))
                try:
                    sentiment = await self._sentiment_facts_provider(
                        symbol,
                        start_date=start_date,
                        end_date=end_date,
                        limit=30,
                    )
                except Exception as error:  # noqa: BLE001 - market-data boundary
                    raise NodeExecutionError(
                        FailureKind.TRANSIENT,
                        f"margin facts failed: {type(error).__name__}: "
                        f"{str(error)[:300]}",
                    ) from error
                fact_evidence.extend(_market_fact_evidence(sentiment))
            self._service_evidence[node.node_id] = [
                item
                for item in (evidence, history_evidence, *fact_evidence)
                if item is not None
            ]
            version = quote.retrieved_at.isoformat()
            reference = VersionReference(
                object_type="MarketSnapshot",
                object_id=context.run_id,
                version=version,
            )
            try:
                await self._evidence_recorder(
                    owner_id=context.owner_id,
                    subject=self._request_intent,
                    run=None,
                    object_type=reference.object_type,
                    object_id=reference.object_id,
                    version=reference.version,
                    content=_market_snapshot_content(
                        quote,
                        evidence,
                        history_evidence,
                    ),
                    conclusion=(
                        f"已从 {quote.provider} 固化 {symbol} 的真实市场快照。"
                    ),
                    provider=quote.provider,
                    generated_at=quote.retrieved_at,
                )
            except Exception as error:  # noqa: BLE001 - persistence boundary
                raise NodeExecutionError(
                    FailureKind.TRANSIENT,
                    f"market snapshot persistence failed: {type(error).__name__}",
                ) from error
            return NodeExecutionOutcome(
                node_id=node.node_id,
                artifact_reference=reference,
                evidence_references=(reference,),
                permissions_used=tuple(sorted(node.tool_allowlist)),
                quality_gate_passed=True,
            )
        if node.service_id == "crawler.context":
            if self._crawler_context_provider is None:
                raise NodeExecutionError(
                    FailureKind.VALIDATION,
                    "deterministic service is not connected: crawler.context",
                )
            try:
                report = await self._crawler_context_provider()
            except Exception as error:  # noqa: BLE001 - crawler boundary
                raise NodeExecutionError(
                    FailureKind.TRANSIENT,
                    f"crawler context failed: {type(error).__name__}: "
                    f"{str(error)[:300]}",
                ) from error
            crawler_evidence = _crawler_evidence(report)
            if not crawler_evidence:
                detail = "; ".join(report.errors) or "crawler returned no records"
                raise NodeExecutionError(
                    FailureKind.VALIDATION,
                    f"crawler context unavailable: {detail[:300]}",
                )
            self._service_evidence[node.node_id] = list(crawler_evidence)
            reference = VersionReference(
                object_type="CrawlerContext",
                object_id=context.run_id,
                version=report.retrieved_at.isoformat(),
            )
            return NodeExecutionOutcome(
                node_id=node.node_id,
                artifact_reference=reference,
                permissions_used=tuple(sorted(node.tool_allowlist)),
                quality_gate_passed=True,
            )
        if node.service_id == "market_alert_context.resolve":
            if self._market_alert_context_provider is None:
                raise NodeExecutionError(
                    FailureKind.VALIDATION,
                    "deterministic service is not connected: "
                    "market_alert_context.resolve",
                )
            symbol = _instrument_symbol(context.input_versions)
            if not symbol:
                raise NodeExecutionError(
                    FailureKind.VALIDATION,
                    "market alert context requires an instrument_context input",
                )
            try:
                alert_context = await self._market_alert_context_provider(symbol)
            except Exception as error:  # noqa: BLE001 - alert-store boundary
                raise NodeExecutionError(
                    FailureKind.TRANSIENT,
                    f"market alert context failed: {type(error).__name__}",
                ) from error
            if alert_context.snapshot is None:
                raise NodeExecutionError(
                    FailureKind.VALIDATION,
                    f"market alert context unavailable: no snapshot for {symbol}",
                )
            evidence = _market_alert_evidence(symbol, alert_context)
            self._service_evidence[node.node_id] = [evidence]
            reference = VersionReference(
                object_type="MarketAlertContext",
                object_id=context.run_id,
                version=alert_context.observed_at.isoformat(),
            )
            try:
                await self._evidence_recorder(
                    owner_id=context.owner_id,
                    subject=self._request_intent,
                    run=None,
                    object_type=reference.object_type,
                    object_id=reference.object_id,
                    version=reference.version,
                    content=_market_alert_context_content(
                        symbol,
                        alert_context,
                        evidence,
                    ),
                    conclusion=_market_alert_conclusion(symbol, alert_context),
                    provider="PandaData",
                    generated_at=alert_context.observed_at,
                )
            except Exception as error:  # noqa: BLE001 - persistence boundary
                raise NodeExecutionError(
                    FailureKind.TRANSIENT,
                    f"market alert context persistence failed: {type(error).__name__}",
                ) from error
            return NodeExecutionOutcome(
                node_id=node.node_id,
                artifact_reference=reference,
                evidence_references=(reference,),
                permissions_used=tuple(sorted(node.tool_allowlist)),
                quality_gate_passed=True,
            )
        if node.service_id == "portfolio.stress_calculate":
            return await self._calculate_portfolio_stress(node, context)
        if node.service_id == "trade_plan.calculate":
            return await self._calculate_trade_plan(node, context)
        if node.service_id == "order_review.calculate":
            return await self._load_order_draft(node, context)
        if node.service_id == "risk.pre_submit":
            return await self._review_order_draft(node, context)
        if node.service_id == "strategy.monitor_compare":
            return await self._compare_strategy_versions(node, context)
        if node.service_id == "workflow.artifact_finalize":
            if not self._agent_runs and self._candidate_response is None:
                raise NodeExecutionError(
                    FailureKind.VALIDATION,
                    "workflow has no real result to finalize",
                )
            combined = _combine_agent_runs(self._agent_runs)
            candidate_response = self._candidate_response
            version = (
                candidate_response.generated_at.isoformat()
                if candidate_response is not None
                else combined.run_id
                if combined is not None
                else f"attempt-{attempt}"
            )
            try:
                await self._evidence_recorder(
                    owner_id=context.owner_id,
                    subject=self._request_intent,
                    run=combined,
                    object_type=context.final_artifact_type,
                    object_id=context.run_id,
                    version=version,
                    content=(
                        evidence_content_from_candidate_response(candidate_response)
                        if candidate_response is not None
                        else None
                    ),
                    conclusion=(
                        candidate_response_conclusion(candidate_response)
                        if candidate_response is not None
                        else None
                    ),
                    provider=(
                        "finance-god-candidate-scoring"
                        if candidate_response is not None
                        else "multi-agent-runtime"
                    ),
                    generated_at=(
                        candidate_response.generated_at
                        if candidate_response is not None
                        else None
                    ),
                )
            except Exception as error:  # noqa: BLE001 - persistence boundary
                raise NodeExecutionError(
                    FailureKind.TRANSIENT,
                    f"workflow evidence persistence failed: {type(error).__name__}",
                ) from error
            return NodeExecutionOutcome(
                node_id=node.node_id,
                artifact_reference=VersionReference(
                    object_type=context.final_artifact_type,
                    object_id=context.run_id,
                    version=version,
                ),
                evidence_references=(
                    VersionReference(
                        object_type=context.final_artifact_type,
                        object_id=context.run_id,
                        version=version,
                    ),
                ),
                permissions_used=tuple(sorted(node.tool_allowlist)),
            )
        raise NodeExecutionError(
            FailureKind.VALIDATION,
            f"deterministic service is not connected: {node.service_id}",
        )

    async def _compare_strategy_versions(
        self,
        node: WorkflowNodeDefinition,
        context: NodeExecutionContext,
    ) -> NodeExecutionOutcome:
        comparisons = _strategy_version_comparisons(context.input_versions)
        serialized_inputs = [
            item.model_dump(mode="json") for item in context.input_versions
        ]
        content: dict[str, object] = {
            "input_versions": serialized_inputs,
            "version_comparisons": comparisons,
            "metric_drift_assessed": False,
            "metric_drift_note": (
                "版本清单仅确认策略输入是否发生变化；指标漂移结论来自受治理的"
                "策略监控 Agent，不从版本字符串推断。"
            ),
        }
        digest = hashlib.sha256(
            json.dumps(content, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()[:20]
        reference = VersionReference(
            object_type="StrategyMonitorComparison",
            object_id=context.run_id,
            version=f"comparison-v1-{digest}",
        )
        evidence = EvidenceRecord(
            identifier=f"strategy-version-comparison-{digest}"[:64],
            source=f"workflow:{context.run_id}"[:256],
            excerpt=(
                f"Compared {len(comparisons)} strategy baseline/current pair(s) "
                f"across {len(context.input_versions)} versioned input(s); "
                "metric drift was not inferred from version identifiers."
            ),
        )
        try:
            await self._evidence_recorder(
                owner_id=context.owner_id,
                subject=self._request_intent,
                run=None,
                object_type=reference.object_type,
                object_id=reference.object_id,
                version=reference.version,
                content=content,
                conclusion=(
                    f"已核对 {len(comparisons)} 组策略基线与当前版本；"
                    "指标漂移以本次受治理 Agent 分析为准。"
                ),
                provider="finance-god-strategy-monitor",
                generated_at=self._clock.now(),
            )
        except Exception as error:  # noqa: BLE001 - persistence boundary
            raise NodeExecutionError(
                FailureKind.TRANSIENT,
                f"strategy comparison persistence failed: {type(error).__name__}",
            ) from error
        self._service_evidence[node.node_id] = [evidence]
        return NodeExecutionOutcome(
            node_id=node.node_id,
            artifact_reference=reference,
            evidence_references=(reference,),
            permissions_used=tuple(sorted(node.tool_allowlist)),
            quality_gate_passed=True,
        )

    async def _calculate_portfolio_stress(
        self,
        node: WorkflowNodeDefinition,
        context: NodeExecutionContext,
    ) -> NodeExecutionOutcome:
        if self._portfolio_provider is None:
            raise NodeExecutionError(
                FailureKind.VALIDATION,
                "deterministic service is not connected: portfolio.stress_calculate",
            )
        try:
            portfolio = await self._portfolio_provider(context.owner_id)
        except Exception as error:  # noqa: BLE001 - application boundary
            raise NodeExecutionError(
                FailureKind.VALIDATION,
                f"portfolio stress input unavailable: {type(error).__name__}: {error}",
            ) from error
        total = sum(
            (position.cost_basis_rmb for position in portfolio.positions),
            Decimal("0"),
        )
        weights = tuple(
            (
                position.instrument_id,
                (position.cost_basis_rmb / total if total > 0 else Decimal("0")),
            )
            for position in portfolio.positions
        )
        largest = max(weights, key=lambda item: item[1], default=None)
        self._portfolio_focus_symbol = largest[0] if largest is not None else None
        reference = VersionReference(
            object_type="PortfolioStressCalculation",
            object_id=context.run_id,
            version=portfolio.as_of.isoformat(),
        )
        content = {
            "account_id": portfolio.account_id,
            "as_of": portfolio.as_of.isoformat(),
            "rule_version": portfolio.rule_version,
            "total_cost_basis_rmb": str(total),
            "position_weights": [
                {"instrument_id": symbol, "cost_weight": str(weight)}
                for symbol, weight in weights
            ],
            "largest_position": (
                None
                if largest is None
                else {
                    "instrument_id": largest[0],
                    "cost_weight": str(largest[1]),
                }
            ),
        }
        await self._evidence_recorder(
            owner_id=context.owner_id,
            subject=self._request_intent,
            run=None,
            object_type=reference.object_type,
            object_id=reference.object_id,
            version=reference.version,
            content=content,
            conclusion="已按仿真持仓成本口径完成组合集中度压力计算。",
            provider="finance-god-portfolio-query",
            generated_at=portfolio.as_of,
        )
        self._service_evidence[node.node_id] = [
            EvidenceRecord(
                identifier="portfolio-stress",
                source="Finance-God simulation portfolio",
                excerpt=(
                    f"positions={len(weights)}; total_cost_basis_rmb={total}; "
                    f"largest={largest}"
                ),
            )
        ]
        if weights:
            if self._market_context_provider is None:
                raise NodeExecutionError(
                    FailureKind.VALIDATION,
                    "portfolio stress market snapshots are not connected",
                )
            symbols = [symbol for symbol, _ in weights]
            try:
                quotes = await self._market_context_provider(symbols)
            except Exception as error:  # noqa: BLE001 - market-data boundary
                raise NodeExecutionError(
                    FailureKind.TRANSIENT,
                    f"portfolio stress market snapshots failed: "
                    f"{type(error).__name__}: {str(error)[:300]}",
                ) from error
            if quotes.errors or len(quotes.quotes) != len(symbols):
                raise NodeExecutionError(
                    FailureKind.VALIDATION,
                    "portfolio stress requires a current snapshot for every position",
                )
            self._service_evidence[node.node_id].append(
                EvidenceRecord(
                    identifier="portfolio-market-snapshots",
                    source="PandaData portfolio position snapshots",
                    excerpt=_compact_json(
                        [
                            {
                                "symbol": quote.symbol,
                                "last": quote.last,
                                "change_percent": quote.change_percent,
                                "provider_time": quote.provider_time,
                                "frequency": quote.frequency,
                                "freshness": quote.freshness,
                            }
                            for quote in quotes.quotes
                        ]
                    ),
                )
            )
        return NodeExecutionOutcome(
            node_id=node.node_id,
            artifact_reference=reference,
            evidence_references=(reference,),
            permissions_used=tuple(sorted(node.tool_allowlist)),
            quality_gate_passed=True,
        )

    async def _calculate_trade_plan(
        self,
        node: WorkflowNodeDefinition,
        context: NodeExecutionContext,
    ) -> NodeExecutionOutcome:
        if self._trade_plan_provider is None:
            raise NodeExecutionError(
                FailureKind.VALIDATION,
                "deterministic service is not connected: trade_plan.calculate",
            )
        symbol = _instrument_symbol(context.input_versions)
        if not symbol:
            raise NodeExecutionError(
                FailureKind.VALIDATION,
                "trade plan requires an instrument_context input",
            )
        try:
            page = await self._trade_plan_provider(
                context.owner_id,
                symbol,
                f"workflow-plan:{context.run_id}",
            )
        except Exception as error:  # noqa: BLE001 - application boundary
            raise NodeExecutionError(
                FailureKind.VALIDATION,
                f"trade plan calculation failed: {type(error).__name__}: {error}",
            ) from error
        plan = page.object
        reference = VersionReference(
            object_type="trade_plan",
            object_id=plan.plan_id,
            version=str(plan.revision),
        )
        await self._evidence_recorder(
            owner_id=context.owner_id,
            subject=self._request_intent,
            run=None,
            object_type=reference.object_type,
            object_id=reference.object_id,
            version=reference.version,
            content=page.model_dump(mode="json"),
            conclusion="已生成版本化仿真交易计划，尚未生成或提交订单。",
            provider="finance-god-trade-plan",
            generated_at=page.generated_at,
        )
        self._service_evidence[node.node_id] = [
            EvidenceRecord(
                identifier="trade-plan",
                source=f"Finance-God trade plan:{plan.plan_id}",
                excerpt=_compact_json(page.model_dump(mode="json")),
            )
        ]
        return NodeExecutionOutcome(
            node_id=node.node_id,
            artifact_reference=reference,
            evidence_references=(reference,),
            permissions_used=tuple(sorted(node.tool_allowlist)),
            pending_actions=("review_trade_plan",),
        )

    async def _load_order_draft(
        self,
        node: WorkflowNodeDefinition,
        context: NodeExecutionContext,
    ) -> NodeExecutionOutcome:
        if self._order_draft_provider is None:
            raise NodeExecutionError(
                FailureKind.VALIDATION,
                "deterministic service is not connected: order_review.calculate",
            )
        reference = _order_draft_reference(context.input_versions)
        try:
            draft = await self._order_draft_provider(
                context.owner_id,
                reference.object_id,
            )
        except Exception as error:  # noqa: BLE001 - execution boundary
            raise NodeExecutionError(
                FailureKind.VALIDATION,
                f"order draft unavailable: {type(error).__name__}: {error}",
            ) from error
        if str(draft.draft.revision) != reference.version:
            raise NodeExecutionError(
                FailureKind.VALIDATION,
                "order draft version changed before workflow review",
            )
        self._order_draft = draft
        self._service_evidence[node.node_id] = [
            EvidenceRecord(
                identifier="order-draft",
                source=f"Finance-God simulation draft:{reference.object_id}",
                excerpt=_compact_json(draft.model_dump(mode="json")),
            )
        ]
        artifact = VersionReference(
            object_type="OrderDraftReviewInput",
            object_id=reference.object_id,
            version=reference.version,
        )
        return NodeExecutionOutcome(
            node_id=node.node_id,
            artifact_reference=artifact,
            permissions_used=tuple(sorted(node.tool_allowlist)),
        )

    async def _review_order_draft(
        self,
        node: WorkflowNodeDefinition,
        context: NodeExecutionContext,
    ) -> NodeExecutionOutcome:
        if self._order_draft_review_provider is None or self._order_draft is None:
            raise NodeExecutionError(
                FailureKind.VALIDATION,
                "deterministic service is not connected: risk.pre_submit",
            )
        input_reference = _order_draft_reference(context.input_versions)
        try:
            reviewed = await self._order_draft_review_provider(
                context.owner_id,
                input_reference.object_id,
                self._order_draft.record_revision,
            )
        except Exception as error:  # noqa: BLE001 - execution boundary
            raise NodeExecutionError(
                FailureKind.VALIDATION,
                f"formal order review failed: {type(error).__name__}: {error}",
            ) from error
        risk = reviewed.risk_result
        if risk is None:
            raise NodeExecutionError(
                FailureKind.VALIDATION,
                "formal order review did not produce a RiskCheckResult",
            )
        risk_reference = VersionReference(
            object_type="RiskCheckResult",
            object_id=risk.risk_check_id,
            version=str(risk.revision),
        )
        result = OrderRiskCheckNodeResult(
            owner_id=context.owner_id,
            input_order_reference=input_reference,
            order_reference=risk.order_version,
            risk_check_reference=risk_reference,
            risk_check=risk,
        )
        return NodeExecutionOutcome(
            node_id=node.node_id,
            artifact_reference=risk_reference,
            permissions_used=tuple(sorted(node.tool_allowlist)),
            deterministic_result=result,
            quality_gate_passed=True,
            pending_actions=("confirm_order_summary",),
        )


class WorkflowWorker:
    """Poll queued WorkflowRuns and drive each through the governed executor."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        runtime_provider: RuntimeProvider,
        evidence_recorder: WorkflowEvidenceRecorder,
        profile_provider: ProfileProvider | None = None,
        candidate_provider: CandidateProvider | None = None,
        market_context_provider: MarketContextProvider | None = None,
        market_history_provider: MarketHistoryProvider | None = None,
        information_facts_provider: MarketFactsProvider | None = None,
        sentiment_facts_provider: MarketFactsProvider | None = None,
        crawler_context_provider: CrawlerContextProvider | None = None,
        market_alert_context_provider: MarketAlertContextProvider | None = None,
        portfolio_provider: PortfolioProvider | None = None,
        trade_plan_provider: TradePlanProvider | None = None,
        order_draft_provider: OrderDraftProvider | None = None,
        order_draft_review_provider: OrderDraftReviewProvider | None = None,
        registry: FormalWorkflowRegistry | None = None,
        catalog: AgentGovernanceCatalog | None = None,
        controls: OpenControls | None = None,
        clock: Clock | None = None,
        batch_size: int = 1,
        wake_event: asyncio.Event | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._runtime_provider = runtime_provider
        self._evidence_recorder = evidence_recorder
        self._profile_provider = profile_provider
        self._candidate_provider = candidate_provider
        self._market_context_provider = market_context_provider
        self._market_history_provider = market_history_provider
        self._information_facts_provider = information_facts_provider
        self._sentiment_facts_provider = sentiment_facts_provider
        self._crawler_context_provider = crawler_context_provider
        self._market_alert_context_provider = market_alert_context_provider
        self._portfolio_provider = portfolio_provider
        self._trade_plan_provider = trade_plan_provider
        self._order_draft_provider = order_draft_provider
        self._order_draft_review_provider = order_draft_review_provider
        self._registry = registry or FormalWorkflowRegistry.build_default()
        self._catalog = catalog or AgentGovernanceCatalog()
        self._controls = controls or OpenControls()
        self._clock = clock or SystemClock()
        self._batch_size = max(1, min(int(batch_size), 20))
        self._wake_event = wake_event
        self._plans = TaskPlanFactory(self._catalog, self._registry)

    async def process_once(self) -> int:
        """Execute up to ``batch_size`` queued runs; return terminal run count."""
        async with self._uow_factory() as uow:
            queued = await uow.workflows.list_queued(limit=self._batch_size)
            await uow.commit()
        finished = 0
        for run_id, owner_id, request_intent, workflow_key in queued:
            try:
                report = await self._execute_one(
                    run_id=run_id,
                    owner_id=owner_id,
                    request_intent=request_intent,
                    workflow_key=workflow_key,
                )
            except Exception:  # noqa: BLE001 - one run must not kill the loop
                _LOGGER.exception("workflow worker failed run %s", run_id)
                continue
            if report is not None:
                finished += 1
                _LOGGER.info(
                    "workflow worker finished %s status=%s",
                    run_id,
                    report.run.status.value,
                )
        return finished

    async def run_forever(
        self,
        *,
        interval_seconds: float,
        stop_event: asyncio.Event,
    ) -> None:
        interval = max(0.2, float(interval_seconds))
        while not stop_event.is_set():
            if self._wake_event is not None:
                self._wake_event.clear()
            try:
                await self.process_once()
            except Exception:  # noqa: BLE001 - keep the daemon observable and alive
                _LOGGER.exception("workflow worker cycle failed")
            if self._wake_event is not None and self._wake_event.is_set():
                continue
            waits = [asyncio.create_task(stop_event.wait())]
            if self._wake_event is not None:
                waits.append(asyncio.create_task(self._wake_event.wait()))
            done, pending = await asyncio.wait(
                waits,
                timeout=interval,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                task.result()

    async def _execute_one(
        self,
        *,
        run_id: str,
        owner_id: str,
        request_intent: str,
        workflow_key: str,
    ) -> WorkflowExecutionReport | None:
        try:
            key = WorkflowKey(workflow_key)
        except ValueError:
            _LOGGER.error("unknown workflow key %s for run %s", workflow_key, run_id)
            return None
        repository = CommittedWorkflowRepository(self._uow_factory)
        run = await repository.get(run_id)
        if run is None or run.status is not WorkflowRunStatus.QUEUED:
            return None
        plan = self._plans.formal(
            plan_id=_plan_id_for(run_id),
            owner_id=owner_id,
            workflow_key=key,
            input_versions=run.input_versions,
            route_reason=_route_reason(request_intent),
        )
        executor = WorkflowExecutor(
            registry=self._registry,
            repository=repository,
            runner=RealWorkflowNodeRunner(
                runtime_provider=self._runtime_provider,
                evidence_recorder=self._evidence_recorder,
                request_intent=request_intent,
                profile_provider=self._profile_provider,
                candidate_provider=self._candidate_provider,
                market_context_provider=self._market_context_provider,
                market_history_provider=self._market_history_provider,
                information_facts_provider=self._information_facts_provider,
                sentiment_facts_provider=self._sentiment_facts_provider,
                crawler_context_provider=self._crawler_context_provider,
                market_alert_context_provider=self._market_alert_context_provider,
                portfolio_provider=self._portfolio_provider,
                trade_plan_provider=self._trade_plan_provider,
                order_draft_provider=self._order_draft_provider,
                order_draft_review_provider=self._order_draft_review_provider,
                clock=self._clock,
            ),
            controls=self._controls,
            clock=self._clock,
        )
        reused_outcomes: tuple[NodeExecutionOutcome, ...] = ()
        record = await repository.get_record(run_id)
        if record is not None and record.get("retry_mode") == "resume_failed":
            parent_run_id = record.get("parent_run_id")
            resumed_from = record.get("resumed_from_node_id")
            if not isinstance(parent_run_id, str) or not isinstance(resumed_from, str):
                raise ValueError("resume_failed run lacks validated lineage")
            parent = await repository.get(parent_run_id)
            if (
                parent is None
                or parent.workflow_key != run.workflow_key
                or parent.workflow_version != run.workflow_version
                or parent.input_versions != run.input_versions
            ):
                raise ValueError("resume_failed parent workflow contract changed")
            audits = await repository.list_execution_audits(parent_run_id)
            completed_by_node = {
                str(audit.payload_json.get("node_id")): audit
                for audit in audits
                if audit.event_type == "node_attempt_completed"
            }
            reusable: list[NodeExecutionOutcome] = []
            terminal: set[str] = set()
            for node in plan.nodes:
                if node.node_id == resumed_from:
                    break
                audit = completed_by_node.get(node.node_id)
                if audit is None or not set(node.dependencies).issubset(terminal):
                    raise ValueError("resume_failed dependency artifacts are incomplete")
                artifact_payload = audit.payload_json.get("artifact")
                if not isinstance(artifact_payload, dict):
                    raise ValueError("resume_failed artifact reference is missing")
                artifact = VersionReference.model_validate(artifact_payload)
                reusable.append(
                    NodeExecutionOutcome(
                        node_id=node.node_id,
                        artifact_reference=artifact,
                        evidence_references=(artifact,),
                        permissions_used=(),
                        quality_gate_passed=True,
                    )
                )
                terminal.add(node.node_id)
                await repository.append_audit(
                    audit_id=f"workflow:{run_id}:reused:{node.node_id}",
                    run_id=run_id,
                    event_type="node_reused",
                    payload_json={
                        "node_id": node.node_id,
                        "artifact": artifact.model_dump(mode="json"),
                        "parent_run_id": parent_run_id,
                    },
                    occurred_at=self._clock.now(),
                    actor_id="workflow-worker",
                    correlation_id=run_id,
                )
            reused_outcomes = tuple(reusable)
        try:
            report = await executor.execute(
                run_id=run_id,
                plan=plan,
                reused_outcomes=reused_outcomes,
            )
        except ConcurrentCommandConflict:
            current = await repository.get(run_id)
            if current is not None and current.status is WorkflowRunStatus.CANCEL_REQUESTED:
                cancelling = current.transition(
                    WorkflowRunStatus.CANCELLING,
                    audit_reference=AuditReference(
                        audit_id=f"workflow:{run_id}:cancelling:{current.revision + 1}",
                        actor_id="workflow-worker",
                        recorded_at=self._clock.now(),
                    ),
                    cancellation_reason=WorkflowCancellationReason.USER_PAUSED,
                )
                current = await repository.compare_and_append(
                    run=cancelling,
                    expected_revision=current.revision,
                    event_type="workflow_cancelling",
                    event_payload={"run_id": run_id, "status": "cancelling"},
                    outbox_topic="workflow.cancelling",
                )
                cancelled = current.transition(
                    WorkflowRunStatus.CANCELLED,
                    audit_reference=AuditReference(
                        audit_id=f"workflow:{run_id}:cancelled:{current.revision + 1}",
                        actor_id="workflow-worker",
                        recorded_at=self._clock.now(),
                    ),
                    cancellation_reason=WorkflowCancellationReason.USER_PAUSED,
                )
                await repository.compare_and_append(
                    run=cancelled,
                    expected_revision=current.revision,
                    event_type="workflow_cancelled",
                    event_payload={"run_id": run_id, "status": "cancelled"},
                    outbox_topic="workflow.cancelled",
                )
                _LOGGER.info("workflow %s cancelled at execution boundary", run_id)
                return None
            _LOGGER.info("workflow %s was claimed or changed by another command", run_id)
            return None
        return report


def _agent_run_id(run_id: str, node_id: str, attempt: int) -> str:
    digest = hashlib.sha256(f"{run_id}:{node_id}:{attempt}".encode()).hexdigest()[:20]
    safe = _PLAN_ID_SAFE.sub("-", run_id).strip("-") or "run"
    return f"wf-{safe[:60]}-{digest}"[:96]


def _input_evidence(context: NodeExecutionContext) -> list[EvidenceRecord]:
    # Prefer E1 for the first seed: structured-prompt schema examples cite E1,
    # matching the direct agent research path.
    records: list[EvidenceRecord] = []
    for index, item in enumerate(context.input_versions, start=1):
        identifier = "E1" if index == 1 else f"input-{index}"
        records.append(
            EvidenceRecord(
                identifier=identifier,
                source=f"{item.object_type}:{item.object_id}"[:256],
                excerpt=(
                    f"Versioned workflow input; object_type={item.object_type}; "
                    f"object_id={item.object_id}; version={item.version}."
                ),
            )
        )
    if not records:
        records.append(
            EvidenceRecord(
                identifier="E1",
                source="workflow:request_intent",
                excerpt="Workflow request with no versioned inputs supplied.",
            )
        )
    return records


def _prior_agent_evidence(runs: dict[str, AgentRun]) -> list[EvidenceRecord]:
    evidence: list[EvidenceRecord] = []
    for node_id in sorted(runs):
        for result in runs[node_id].results:
            evidence.extend(result.evidence)
            evidence.append(
                EvidenceRecord(
                    identifier=f"prior-{node_id}-{len(evidence)}"[:64],
                    source=result.agent_id[:256],
                    excerpt=(
                        " | ".join(claim.statement for claim in result.claims)
                        or result.summary
                    )[:4_000],
                )
            )
    return _dedupe_evidence(evidence)


def _combine_agent_runs(runs: dict[str, AgentRun]) -> AgentRun | None:
    if not runs:
        return None
    ordered = [runs[node_id] for node_id in sorted(runs)]
    combined_id = ordered[-1].run_id
    return AgentRun(
        run_id=combined_id,
        plan=AgentPlan(
            run_id=combined_id,
            assignments=[
                assignment for run in ordered for assignment in run.plan.assignments
            ],
            notices=[notice for run in ordered for notice in run.plan.notices],
        ),
        results=[result for run in ordered for result in run.results],
    )


def _market_snapshot_content(
    quote: MarketQuote,
    evidence: EvidenceRecord,
    history_evidence: EvidenceRecord | None = None,
) -> dict[str, object]:
    sources = [
        {
            "identifier": evidence.identifier,
            "source": evidence.source,
            "excerpt": evidence.excerpt,
        }
    ]
    if history_evidence is not None:
        sources.append(
            {
                "identifier": history_evidence.identifier,
                "source": history_evidence.source,
                "excerpt": history_evidence.excerpt,
            }
        )
    return {
        "facts": [
            {
                "kind": "fact",
                "statement": (
                    f"{quote.symbol} 最新价 {quote.last}，"
                    f"{_quote_change_text(quote.change_percent)}，"
                    f"上游时间 {quote.provider_time}，"
                    f"交易时段对齐状态 {quote.session_alignment}。"
                ),
                "author_agent_id": "financegod:market-snapshot",
                "evidence_ids": [evidence.identifier],
                "unknowns": [],
                "invalidation_conditions": [
                    "PandaData 发布更新的上游时间后，该快照失效。"
                ],
            }
        ],
        "inferences": [],
        "counterpoints": [],
        "unknowns": [],
        "invalidation_conditions": ["PandaData 发布更新的上游时间后，该快照失效。"],
        "sources": sources,
        "agent_nodes": [],
        "notices": [],
    }


def _market_history_evidence(
    symbol: str,
    start_date: str,
    end_date: str,
    result: MarketBarsResult,
) -> EvidenceRecord:
    rows = "; ".join(
        (
            f"{bar.time}:open={bar.open},high={bar.high},low={bar.low},"
            f"close={bar.close},volume={bar.volume},provider_time={bar.provider_time},"
            f"freshness={bar.freshness}"
        )
        for bar in result.bars
    )
    return EvidenceRecord(
        identifier=f"target-market-bars-{symbol}",
        source=f"PandaData:{symbol}:daily:{start_date}-{end_date}",
        excerpt=(
            f"requested_range={start_date}-{end_date}; frequency={result.frequency}; "
            f"row_count={len(result.bars)}; bars=[{rows}]"
        ),
    )


def _research_quarter_range(observed_at: datetime) -> tuple[str, str]:
    local = observed_at.astimezone(observed_at.tzinfo)
    end_index = local.year * 4 + (local.month - 1) // 3
    start_index = end_index - 3
    start_year, start_offset = divmod(start_index, 4)
    end_year, end_offset = divmod(end_index, 4)
    return (
        f"{start_year}q{start_offset + 1}",
        f"{end_year}q{end_offset + 1}",
    )


def _market_fact_evidence(batch: MarketFactBatch) -> list[EvidenceRecord]:
    rows = []
    for fact in batch.facts:
        fields = {field.name: field.value for field in fact.fields}
        rows.append(
            {
                "data_time": fact.source.data_time.isoformat(),
                "provider_time": (
                    fact.source.provider_published_at.isoformat()
                    if fact.source.provider_published_at is not None
                    else None
                ),
                "endpoint": fact.source.endpoint,
                "freshness": fact.freshness.status.value,
                "fields": fields,
            }
        )
    return [
        EvidenceRecord(
            identifier=f"{batch.fact_kind}-{batch.symbol}"[:64],
            source=f"PandaData:{batch.fact_kind}:{batch.symbol}",
            excerpt=_compact_json(
                {
                    "fact_kind": batch.fact_kind,
                    "symbol": batch.symbol,
                    "requested_at": batch.requested_at.isoformat(),
                    "row_count": len(rows),
                    "records": rows,
                }
            ),
        )
    ]


def _crawler_evidence(report: CrawlerResult) -> list[EvidenceRecord]:
    evidence: list[EvidenceRecord] = []
    if report.news:
        evidence.append(
            EvidenceRecord(
                identifier="crawler-news",
                source="Finance-God crawler/public financial news",
                excerpt=_compact_json(
                    {
                        "retrieved_at": report.retrieved_at.isoformat(),
                        "scope": "broad-market-and-industry; not automatically symbol-specific",
                        "records": [
                            {
                                "title": item.title,
                                "summary": item.summary,
                                "source": item.source,
                                "url": item.url,
                                "publish_time": (
                                    item.publish_time.isoformat()
                                    if item.publish_time is not None
                                    else None
                                ),
                                "sector": item.sector,
                            }
                            for item in report.news[:10]
                        ],
                    }
                ),
            )
        )
    if report.sentiment is not None:
        evidence.append(
            EvidenceRecord(
                identifier="crawler-market-sentiment",
                source=f"Finance-God crawler:{report.sentiment.data_source}",
                excerpt=_compact_json(report.sentiment.model_dump(mode="json")),
            )
        )
    if report.errors:
        evidence.append(
            EvidenceRecord(
                identifier="crawler-limitations",
                source="Finance-God crawler diagnostics",
                excerpt=_compact_json(
                    {
                        "retrieved_at": report.retrieved_at.isoformat(),
                        "errors": report.errors,
                    }
                ),
            )
        )
    return evidence


def _compact_json(value: object, *, limit: int = 3_950) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return serialized[:limit]


def _quote_change_text(change_percent: Decimal | None) -> str:
    if change_percent is None:
        return "涨跌幅不可用"
    return f"涨跌幅 {(change_percent * Decimal('100')):.2f}%"


def _market_alert_evidence(
    symbol: str,
    context: MarketAlertContext,
) -> EvidenceRecord:
    snapshot = context.snapshot
    if snapshot is None:
        raise ValueError("market alert evidence requires a snapshot")
    alert = context.latest_alert
    alert_excerpt = (
        "alert_status=triggered; "
        f"alert_id={alert.alert_id}; kind={alert.kind.value}; "
        f"severity={alert.severity.value}; detected_at={alert.detected_at.isoformat()}"
        if alert is not None
        else "alert_status=none_recorded"
    )
    return EvidenceRecord(
        identifier=f"market-alert-context-{symbol}",
        source=f"PandaData market monitor:{symbol}",
        excerpt=(
            f"symbol={symbol}; last={snapshot.last}; "
            f"change_percent={snapshot.change_percent}; "
            f"provider_time={snapshot.provider_time}; "
            f"frequency={snapshot.frequency}; freshness={snapshot.freshness}; "
            f"observed_at={context.observed_at.isoformat()}; {alert_excerpt}"
        ),
    )


def _market_alert_conclusion(
    symbol: str,
    context: MarketAlertContext,
) -> str:
    alert = context.latest_alert
    if alert is None:
        return (
            f"截至 {context.observed_at.isoformat()}，系统未记录 {symbol} "
            "的重大行情提醒。"
        )
    return (
        f"{symbol} 最近一条重大行情提醒为 {alert.alert_id}，"
        f"触发时间 {alert.detected_at.isoformat()}。"
    )


def _market_alert_context_content(
    symbol: str,
    context: MarketAlertContext,
    evidence: EvidenceRecord,
) -> dict[str, object]:
    statement = _market_alert_conclusion(symbol, context)
    return {
        "facts": [
            {
                "kind": "fact",
                "statement": statement,
                "author_agent_id": "financegod:market-alert-context",
                "evidence_ids": [evidence.identifier],
                "unknowns": [],
                "invalidation_conditions": [
                    "市场监控器记录更新的快照或提醒后，该结论失效。"
                ],
            }
        ],
        "inferences": [],
        "counterpoints": [],
        "unknowns": [],
        "invalidation_conditions": ["市场监控器记录更新的快照或提醒后，该结论失效。"],
        "sources": [
            {
                "identifier": evidence.identifier,
                "source": evidence.source,
                "excerpt": evidence.excerpt,
            }
        ],
        "agent_nodes": [],
        "notices": [],
    }


def _extend_evidence(evidence: list[EvidenceRecord], result, index: int):
    # One compact prior record per agent keeps sequential research under the
    # claim evidence_ids cap (16) while still chaining summaries.
    extended = _dedupe_evidence([*evidence, *result.evidence])
    if result.claims:
        excerpt = " | ".join(claim.statement for claim in result.claims)[:4_000]
    else:
        excerpt = result.summary[:4_000]
    extended.append(
        EvidenceRecord(
            identifier=f"prior-{index}",
            source=result.agent_id[:256],
            excerpt=excerpt,
        )
    )
    return _dedupe_evidence(extended)


def _dedupe_evidence(records: list[EvidenceRecord]) -> list[EvidenceRecord]:
    unique: list[EvidenceRecord] = []
    seen: set[str] = set()
    for record in records:
        if record.identifier in seen:
            continue
        seen.add(record.identifier)
        unique.append(record)
    return unique[-50:]


def _task_type(task_types: set[str]) -> str:
    return "research" if "research" in task_types else sorted(task_types)[0]


def _asset_kind(inputs: tuple[VersionReference, ...]) -> AssetKind:
    object_types = {item.object_type.lower() for item in inputs}
    if any("portfolio" in item for item in object_types):
        return AssetKind.PORTFOLIO
    if any("fund" in item for item in object_types):
        return AssetKind.FUND
    if any("market" in item for item in object_types):
        return AssetKind.MARKET
    if any("instrument" in item or "equity" in item for item in object_types):
        return AssetKind.EQUITY
    return AssetKind.OTHER


def _instrument_symbol(inputs: tuple[VersionReference, ...]) -> str:
    return next(
        (item.object_id for item in inputs if item.object_type == "instrument_context"),
        "",
    )


def _strategy_version_comparisons(
    inputs: tuple[VersionReference, ...],
) -> list[dict[str, object]]:
    baselines = {
        item.object_id: item
        for item in inputs
        if item.object_type == "strategy_baseline"
    }
    current = {
        item.object_id: item
        for item in inputs
        if item.object_type == "strategy_snapshot"
    }
    return [
        {
            "object_id": object_id,
            "baseline_version": baselines[object_id].version,
            "current_version": current[object_id].version,
            "version_changed": (
                baselines[object_id].version != current[object_id].version
            ),
        }
        for object_id in sorted(baselines.keys() & current.keys())
    ]


def _order_draft_reference(
    inputs: tuple[VersionReference, ...],
) -> VersionReference:
    reference = next(
        (item for item in inputs if item.object_type == "order_draft"),
        None,
    )
    if reference is None:
        raise NodeExecutionError(
            FailureKind.VALIDATION,
            "order review requires an order_draft input version",
        )
    return reference


def _provider_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise NodeExecutionError(
            FailureKind.VALIDATION,
            "market quote provider_time is not an ISO-8601 timestamp",
        ) from error
    if parsed.tzinfo is None:
        raise NodeExecutionError(
            FailureKind.VALIDATION,
            "market quote provider_time must be timezone-aware",
        )
    return parsed


def _agent_payload(
    agent_id: str,
    context: NodeExecutionContext,
    now,
) -> dict[str, object]:
    symbol = _instrument_symbol(context.input_versions)
    end_date = now.date()
    start_date = end_date - timedelta(days=30)
    is_synthesis_agent = "manager" in agent_id.casefold()
    contribution_rule = (
        "你是末端综合节点：必须形成一份可独立阅读的完整中文综合结论，合并等价内容，"
        "保留相互冲突的证据并降低结论置信度。"
        if is_synthesis_agent
        else "只补充本角色新增的信息，不要复述已有 Agent 的等价结论。"
    )
    common = {
        "subject": symbol or context.run_id,
        "start_date": start_date.strftime("%Y%m%d"),
        "end_date": end_date.strftime("%Y%m%d"),
        "response_language": "zh-CN",
        "response_requirements": natural_chinese_requirement(
            "摘要、事实、推断、未知项、失效条件和待审核动作均使用简体中文；"
            "保留证券代码、证据 ID 和必要的字段名。",
            contribution_rule,
            "涨跌幅必须说明计算区间或基准，无法从证据确认时明确标为未知；"
            "数据时效必须区分上游时间、抓取时间、频率和 freshness 状态。",
        ),
    }
    if agent_id == "quantskills:agent-market-regime-monitor":
        return {
            **common,
            "kind": "market_regime",
            "symbol": symbol,
            "index_symbol": _MARKET_REGIME_INDEX,
            "option_underlying": _OPTION_VOLATILITY_UNDERLYING,
        }
    if agent_id == "quantskills:agent-crowding-risk-monitor":
        return {**common, "kind": "crowding_risk", "symbol": symbol}
    if agent_id == "quantskills:agent-derivatives-skew-sentiment-monitor":
        return {
            **common,
            "kind": "derivatives_iv_premium",
            "option_underlying": _OPTION_VOLATILITY_UNDERLYING,
            "option_symbols": [],
        }
    if agent_id == "quantskills:agent-correlation-break-research":
        raise ValueError(
            "correlation-break workflow requires explicit future_symbols input"
        )
    return common


def _plan_id_for(run_id: str) -> str:
    safe = _PLAN_ID_SAFE.sub("-", run_id).strip("-") or "run"
    return f"worker-{safe}"[:160]


def _route_reason(request_intent: str) -> str:
    return ((request_intent or "").strip() or "workflow_worker")[:500]


__all__ = [
    "CONNECTED_DETERMINISTIC_SERVICES",
    "OpenControls",
    "RealWorkflowNodeRunner",
    "WorkflowWorker",
    "WorkflowWorkerUnitOfWork",
    "worker_supports",
]
