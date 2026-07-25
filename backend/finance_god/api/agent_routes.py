"""HTTP surface for the unified Multi-Agent research runtime.

These routes expose the orchestration runtime as an on-demand research
capability. They never fabricate AI output: when the runtime is not
configured or an execution fails, the caller receives an explicit error so
the frontend can render a visible failure state instead of a default answer.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from time import monotonic
from typing import Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from research_runtime import AgentRequest, AssetKind
from research_runtime.contracts import AgentRun
from research_runtime.models import EvidenceRecord
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from finance_god.agents.contracts import WorkflowKey
from finance_god.api.auth import AuthenticationError, OwnerResolver
from finance_god.api.desk_intent import (
    requests_trade_form_prefill,
    requires_desk_workflow,
    select_desk_workflow,
)
from finance_god.api.desk_routes import (
    SAFE_UI_ACTIONS,
    SuitabilityProfileProjection,
    project_suitability_profile,
    validate_action_parameters,
)
from finance_god.application.workflow_worker import worker_supports
from finance_god.orchestration.workflow_registry import WorkflowDefinition


class AgentRuntimeUnavailable(RuntimeError):
    """Raised when the Multi-Agent runtime cannot be configured."""


class UnsafeUiActionsError(ValueError):
    """Raised after the Agent exhausts its safe UI-action proposal attempts."""


class _AgentRuntime(Protocol):  # pragma: no cover - typing helper only
    async def run(self, request: AgentRequest) -> AgentRun: ...

    async def compose_desk_turn(
        self,
        *,
        message: str,
        section: str,
        symbol: str,
        mode: str,
        workflow_title: str | None,
        action_catalog: tuple[dict[str, str], ...],
        profile_projection: dict[str, object],
        portfolio_projection: dict[str, object],
        include_answer: bool = True,
    ) -> dict[str, object]: ...

    def stream_desk_answer(
        self,
        *,
        message: str,
        section: str,
        symbol: str,
    ) -> AsyncIterator[str]: ...

    def list_agents(self) -> tuple: ...


RuntimeProvider = Callable[[], Awaitable["_AgentRuntime"]]
# (owner_id, subject, run) -> None. A successful direct response is not
# returned until its evidence is durable.
EvidenceRecorder = Callable[[str, str, AgentRun], Awaitable[None]]
# owner_id -> compact investor-profile context, or None when the caller has no
# completed profile. The value is injected as agent context so the planner and
# every prompt agent can tailor their reasoning to the user's mandate.
ProfileProvider = Callable[[str], Awaitable["dict | None"]]
PortfolioProvider = Callable[[str], Awaitable[object]]
LearningContextProvider = Callable[
    [str, str, str],
    Awaitable[list[EvidenceRecord]],
]
WorkflowDefinitionProvider = Callable[[str], WorkflowDefinition]
DecisionRecorder = Callable[[str, str, str], Awaitable[None]]

# Stable identifier for the synthetic evidence record carrying the profile so
# research claims can cite it and it never collides with caller-supplied ids.
_PROFILE_EVIDENCE_ID = "investor-profile"
# Seed evidence when the caller supplies none. TradingAgents prompt adapters
# require at least one citable record; the subject itself is the request fact.
# Use E1 (not a prose id): the structured-prompt schema example cites ["E1"],
# and models often copy that token when only one record is present.
_SUBJECT_EVIDENCE_ID = "E1"
_AGENT_EVIDENCE_LIMIT = 50
_LOGGER = logging.getLogger(__name__)


class _APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _EvidenceInput(_APIModel):
    identifier: str = Field(min_length=1, max_length=64)
    source: str = Field(min_length=1, max_length=256)
    excerpt: str = Field(min_length=1, max_length=4_000)


class AgentResearchRequest(_APIModel):
    """Public request contract for an on-demand research run."""

    subject: str = Field(min_length=1, max_length=500)
    task_type: str = Field(default="research", min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
    asset_kind: AssetKind = AssetKind.EQUITY
    scope: str | None = Field(default=None, max_length=64)
    evidence: list[_EvidenceInput] = Field(default_factory=list, max_length=50)
    max_agents: int = Field(default=6, ge=1, le=43)


class DeskAgentDecisionRequest(_APIModel):
    """Server-owned routing input for the persistent desk Agent."""

    message: str = Field(min_length=1, max_length=500)
    section: Literal["information", "portfolio", "watchlist", "trading", "review"]
    symbol: str = Field(min_length=1, max_length=160)
    context_version: str = Field(min_length=1, max_length=80)
    active_workflow: bool = False
    order_draft_id: str | None = Field(default=None, min_length=1, max_length=160)
    order_draft_version: str | None = Field(
        default=None,
        min_length=1,
        max_length=80,
    )

    @model_validator(mode="after")
    def require_complete_order_reference(self):
        if (self.order_draft_id is None) != (self.order_draft_version is None):
            raise ValueError(
                "order_draft_id and order_draft_version must be supplied together"
            )
        return self


class DeskAgentDecisionResponse(_APIModel):
    decision_id: str
    decision_source: Literal["agent_generated_policy_approved"]
    mode: Literal["answer", "workflow"]
    message: str
    workflow_key: str | None = None
    workflow_title: str | None = None
    routing_reason: str
    expected_stages: tuple[str, ...] = ()
    can_start: bool
    answer_text: str | None = None
    ui_actions: tuple["DeskProposedUiAction", ...] = ()


class DeskAgentPreviewResponse(_APIModel):
    mode: Literal["answer", "workflow"]
    workflow_key: str | None = None
    workflow_title: str | None = None
    expected_roles: tuple[str, ...]
    artifact_types: tuple[str, ...]
    can_start: bool


class DeskProposedUiAction(_APIModel):
    action_id: str
    parameters: dict[str, str] = {}
    context_version: str


_EXPLICIT_UI_ACTION_PATTERN = re.compile(
    r"(打开|切换|切到|进入|跳转到)(总览|持仓|自选|交易)"
    r"|选择.{0,16}(标的|股票)"
    r"|(?:加入|添加|放入).{0,12}自选"
    r"|刷新(行情|市场)"
    r"|预填|填入.{0,12}(草稿|买入|卖出)"
    r"|(?:填写|填入|预填|生成).{0,12}(交易单|下单表单|订单草稿)"
    r"|设置.{0,12}(筛选|排序)"
    r"|打开.{0,16}(记录|提醒|计划|产物)"
)


def _requests_ui_action(message: str) -> bool:
    return _EXPLICIT_UI_ACTION_PATTERN.search(message) is not None


def _validated_ui_actions(
    proposed: object,
    payload: DeskAgentDecisionRequest,
) -> tuple[DeskProposedUiAction, ...]:
    if not isinstance(proposed, list):
        raise ValueError("Agent proposed an invalid action batch")
    if proposed and not _requests_ui_action(payload.message):
        _LOGGER.warning(
            "discarding unsolicited desk UI actions for a non-UI user request"
        )
        return ()
    catalog_ids = {item["id"] for item in SAFE_UI_ACTIONS}
    validated: list[DeskProposedUiAction] = []
    for raw in proposed:
        action_id = raw.get("action_id")
        parameters = raw.get("parameters", {})
        if not isinstance(action_id, str) or action_id not in catalog_ids:
            raise ValueError("Agent proposed an action outside the safe catalog")
        if not isinstance(parameters, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in parameters.items()
        ):
            raise ValueError("Agent proposed invalid action parameters")
        if validate_action_parameters(action_id, parameters) is not None:
            raise ValueError("Agent proposed an action rejected by parameter policy")
        validated.append(
            DeskProposedUiAction(
                action_id=action_id,
                parameters=parameters,
                context_version=payload.context_version,
            )
        )
    return tuple(validated)


async def _compose_turn_with_safe_ui_actions(
    runtime: _AgentRuntime,
    *,
    payload: DeskAgentDecisionRequest,
    workflow_title: str | None,
    profile_projection: dict[str, object],
    portfolio_projection: dict[str, object],
    include_answer: bool = True,
) -> tuple[dict[str, object], tuple[DeskProposedUiAction, ...]]:
    """Retry one malformed action proposal without weakening the action policy."""
    if workflow_title is not None and requests_trade_form_prefill(payload.message):
        return (
            {
                "routing_reason": (
                    f"该任务先执行“{workflow_title}”，完成后再用版本化交易计划预填交易单。"
                ),
                "answer_text": None,
                "ui_actions": [],
            },
            (),
        )
    if workflow_title is not None and not _requests_ui_action(payload.message):
        return (
            {
                "routing_reason": f"该任务需要启动“{workflow_title}”工作流。",
                "answer_text": None,
                "ui_actions": [],
            },
            (),
        )
    for attempt in range(2):
        turn = await runtime.compose_desk_turn(
            message=payload.message,
            section=payload.section,
            symbol=payload.symbol,
            mode="answer" if workflow_title is None else "workflow",
            workflow_title=workflow_title,
            action_catalog=SAFE_UI_ACTIONS,
            profile_projection=profile_projection,
            portfolio_projection=portfolio_projection,
            include_answer=include_answer,
        )
        try:
            return turn, _validated_ui_actions(turn.get("ui_actions"), payload)
        except ValueError as error:
            if attempt == 0:
                _LOGGER.warning(
                    "desk Agent proposed invalid UI actions; retrying structured turn",
                    exc_info=True,
                )
                continue
            raise UnsafeUiActionsError(str(error)) from error
    raise AssertionError("unreachable")


def _error(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message, "trace_id": uuid4().hex}},
        status_code=status_code,
    )


def _profile_evidence_excerpt(profile: dict) -> str:
    """Render a compact, human-readable investor-profile summary for prompts."""
    parts: list[str] = []
    archetype = profile.get("archetype_title") or profile.get("archetype_code")
    if archetype:
        parts.append(f"archetype={archetype}")
    if profile.get("risk_level"):
        parts.append(f"risk_level={profile['risk_level']}")
    if profile.get("loss_tolerance_percent") is not None:
        parts.append(f"loss_tolerance={profile['loss_tolerance_percent']}%")
    if profile.get("style_name"):
        parts.append(f"style={profile['style_name']}")
    if profile.get("selected_direction"):
        parts.append(f"selected_direction={profile['selected_direction']}")
    elif profile.get("recommended_directions"):
        joined = ", ".join(str(item) for item in profile["recommended_directions"])
        parts.append(f"recommended_directions={joined}")
    if profile.get("education_only"):
        parts.append("education_only=true")
    return "; ".join(parts) if parts else "Investor profile available."


async def _load_profile_projection(
    profile_provider: ProfileProvider | None,
    owner_id: str,
) -> dict[str, object]:
    """Load the same safe profile projection used by desk bootstrap and research."""

    if profile_provider is None:
        projection = SuitabilityProfileProjection(available=False, degraded=True)
    else:
        try:
            raw_profile = await profile_provider(owner_id)
        except Exception:  # noqa: BLE001 - expose degraded context to the Agent
            projection = SuitabilityProfileProjection(available=False, degraded=True)
        else:
            projection = project_suitability_profile(raw_profile)
    return projection.model_dump(mode="json")


async def _load_portfolio_projection(
    portfolio_provider: PortfolioProvider | None,
    owner_id: str,
) -> dict[str, object]:
    """Load a minimal simulation-portfolio projection for desk conversation."""

    unavailable = {
        "available": False,
        "degraded": portfolio_provider is None,
        "simulation": True,
        "positions": [],
    }
    if portfolio_provider is None:
        return unavailable
    try:
        portfolio = await portfolio_provider(owner_id)
    except LookupError:
        return unavailable
    except Exception:  # noqa: BLE001 - expose degraded context to the Agent
        return {**unavailable, "degraded": True}

    positions = [
        {
            "instrument_id": str(position.instrument_id),
            "quantity": str(position.quantity),
            "available_quantity": str(position.available_quantity),
            "cost_basis_rmb": str(position.cost_basis_rmb),
            "average_cost_rmb": (
                str(position.average_cost_rmb)
                if position.average_cost_rmb is not None
                else None
            ),
            "realized_pnl_rmb": str(position.realized_pnl_rmb),
        }
        for position in getattr(portfolio, "positions", ())
    ]
    return {
        "available": True,
        "degraded": False,
        "simulation": True,
        "as_of": str(portfolio.as_of),
        "rule_version": str(portfolio.rule_version),
        "positions": positions,
        "realized_pnl_rmb": str(portfolio.realized_pnl_rmb),
    }


def _merge_evidence(
    primary: list[EvidenceRecord],
    contextual: list[EvidenceRecord],
) -> list[EvidenceRecord]:
    """Keep caller evidence first, then fill remaining AgentRequest capacity."""

    merged: list[EvidenceRecord] = []
    seen: set[str] = set()
    for record in [*primary, *contextual]:
        if record.identifier in seen:
            continue
        seen.add(record.identifier)
        merged.append(record)
        if len(merged) >= _AGENT_EVIDENCE_LIMIT:
            break
    return merged


def create_agent_routes(
    *,
    runtime_provider: RuntimeProvider,
    owner_resolver: OwnerResolver,
    evidence_recorder: EvidenceRecorder | None = None,
    profile_provider: ProfileProvider | None = None,
    portfolio_provider: PortfolioProvider | None = None,
    learning_context_provider: LearningContextProvider | None = None,
    workflow_definition_provider: WorkflowDefinitionProvider | None = None,
    decision_recorder: DecisionRecorder | None = None,
) -> list[Route]:
    """Build the ``/agent/*`` routes bound to a lazy runtime provider."""

    async def research(request: Request) -> JSONResponse:
        try:
            owner_id = await owner_resolver(request)
        except AuthenticationError as error:
            return _error("UNAUTHORIZED", str(error), 401)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - malformed JSON is a client error
            return _error("AI_INVALID_REQUEST", "The request body is not valid JSON.", 400)
        try:
            payload = AgentResearchRequest.model_validate(body)
        except ValidationError as error:
            return _error("AI_INVALID_REQUEST", error.errors().__str__(), 400)
        try:
            runtime = await runtime_provider()
        except AgentRuntimeUnavailable as error:
            return _error("AI_RUNTIME_UNAVAILABLE", str(error), 503)
        # Load the caller's investor profile so the planner and every prompt
        # agent reason against the user's mandate. Never inject profile data
        # into routing ``tags``: that would silently change agent selection.
        profile: dict | None = None
        if profile_provider is not None:
            try:
                raw_profile = await profile_provider(owner_id)
            except Exception:  # noqa: BLE001 - profile context is best-effort
                raw_profile = None
            # Only inject SuitabilityProfileProjection fields — never raw
            # questionnaire, objective_profile, dimension_scores, or secrets.
            if raw_profile:
                projection = project_suitability_profile(raw_profile)
                if projection.available:
                    profile = projection.model_dump(mode="json")
        evidence = [
            EvidenceRecord(
                identifier=item.identifier,
                source=item.source,
                excerpt=item.excerpt,
            )
            for item in payload.evidence
        ]
        request_payload: dict = {}
        contextual_evidence: list[EvidenceRecord] = []
        if profile:
            request_payload["investor_profile"] = profile
            supplied_ids = {item.identifier for item in evidence}
            if _PROFILE_EVIDENCE_ID not in supplied_ids:
                contextual_evidence.append(
                    EvidenceRecord(
                        identifier=_PROFILE_EVIDENCE_ID,
                        source="Finance-God investor profile",
                        excerpt=_profile_evidence_excerpt(profile),
                    ),
                )
        if learning_context_provider is not None:
            try:
                contextual_evidence.extend(
                    await learning_context_provider(
                        payload.subject,
                        payload.task_type,
                        payload.asset_kind.value,
                    )
                )
            except Exception:  # noqa: BLE001 - optional context must not hide the run
                _LOGGER.exception("verified learning context is unavailable")
        evidence = _merge_evidence(evidence, contextual_evidence)
        if not evidence:
            # Structured prompt agents reject empty evidence. Seed a single
            # request-subject record so on-demand research can run without the
            # caller pre-staging market excerpts; claims must still cite it.
            seed_parts = [payload.subject.strip()]
            if payload.scope:
                seed_parts.append(f"scope={payload.scope.strip()}")
            seed_parts.append(f"task_type={payload.task_type}")
            seed_parts.append(f"asset_kind={payload.asset_kind.value}")
            evidence = [
                EvidenceRecord(
                    identifier=_SUBJECT_EVIDENCE_ID,
                    source="Finance-God research request",
                    excerpt="; ".join(seed_parts),
                )
            ]
        agent_request = AgentRequest(
            run_id=f"fg-{uuid4().hex}",
            subject=payload.subject,
            task_type=payload.task_type,
            asset_kind=payload.asset_kind,
            evidence=evidence,
            payload=request_payload,
            max_agents=payload.max_agents,
        )
        try:
            run = await runtime.run(agent_request)
        except Exception:  # noqa: BLE001 - public HTTP error boundary, no leak
            _LOGGER.exception(
                "agent research runtime failed run_id=%s subject=%s",
                agent_request.run_id,
                payload.subject,
            )
            return _error(
                "AI_RUNTIME_ERROR",
                "The research run failed. No conclusion was produced.",
                502,
            )
        if evidence_recorder is not None:
            try:
                await evidence_recorder(owner_id, payload.subject, run)
            except Exception:  # noqa: BLE001 - explicit public failure boundary
                _LOGGER.exception(
                    "agent evidence persistence failed run_id=%s subject=%s",
                    agent_request.run_id,
                    payload.subject,
                )
                return _error(
                    "AI_EVIDENCE_PERSISTENCE_FAILED",
                    "The answer was not returned because its evidence could not be saved.",
                    502,
                )
        return JSONResponse(run.model_dump(mode="json"), status_code=200)

    async def catalog(request: Request) -> JSONResponse:
        try:
            await owner_resolver(request)
        except AuthenticationError as error:
            return _error("UNAUTHORIZED", str(error), 401)
        try:
            runtime = await runtime_provider()
        except AgentRuntimeUnavailable as error:
            return _error("AI_RUNTIME_UNAVAILABLE", str(error), 503)
        try:
            agents = runtime.list_agents()
        except Exception:  # noqa: BLE001 - public HTTP error boundary
            return _error("AI_RUNTIME_ERROR", "The agent catalog is unavailable.", 502)
        return JSONResponse(
            {
                "agents": [
                    {
                        "agent_id": agent.agent_id,
                        "title": agent.title,
                        "source": agent.source,
                        "task_types": sorted(agent.task_types),
                        "asset_kinds": sorted(kind.value for kind in agent.asset_kinds),
                    }
                    for agent in agents
                ],
            },
            status_code=200,
        )

    async def decide_for_desk(request: Request) -> JSONResponse:
        try:
            owner_id = await owner_resolver(request)
        except AuthenticationError as error:
            return _error("UNAUTHORIZED", str(error), 401)
        try:
            payload = DeskAgentDecisionRequest.model_validate(await request.json())
        except (ValidationError, ValueError) as error:
            return _error("AI_INVALID_REQUEST", str(error), 400)
        try:
            runtime = await runtime_provider()
        except AgentRuntimeUnavailable as error:
            return _error("AI_RUNTIME_UNAVAILABLE", str(error), 503)
        direct_answer = _is_direct_answer(payload.message)
        workflow_key = None
        definition = None
        if not direct_answer:
            workflow_key = select_desk_workflow(
                payload.message,
                section=payload.section,
            )
            if workflow_definition_provider is None:
                return _error(
                    "AI_RUNTIME_UNAVAILABLE",
                    "The workflow registry is unavailable.",
                    503,
                )
            definition = workflow_definition_provider(workflow_key.value)
        try:
            profile_projection = await _load_profile_projection(
                profile_provider,
                owner_id,
            )
            portfolio_projection = await _load_portfolio_projection(
                portfolio_provider,
                owner_id,
            )
            turn_started = monotonic()
            turn, ui_actions = await _compose_turn_with_safe_ui_actions(
                runtime,
                payload=payload,
                workflow_title=definition.title if definition is not None else None,
                profile_projection=profile_projection,
                portfolio_projection=portfolio_projection,
            )
            routing_reason = str(turn.get("routing_reason", "")).strip()
            if not routing_reason:
                raise ValueError("Agent returned an empty routing reason")
            _LOGGER.info(
                "desk turn completed mode=%s elapsed_ms=%d",
                "answer" if direct_answer else "workflow",
                round((monotonic() - turn_started) * 1_000),
            )
        except UnsafeUiActionsError as error:
            _LOGGER.exception("desk UI action proposal failed")
            return _error(
                "AI_ACTION_PROPOSAL_FAILED",
                f"Agent could not produce safe UI actions: {type(error).__name__}",
                502,
            )
        except Exception as error:  # noqa: BLE001 - model/policy boundary
            _LOGGER.exception("desk turn Agent failed")
            return _error(
                "AI_DECISION_FAILED",
                f"Agent could not produce a valid desk turn: {type(error).__name__}",
                502,
            )
        if direct_answer:
            answer_text = turn.get("answer_text")
            if not isinstance(answer_text, str) or not answer_text.strip():
                return _error(
                    "AI_DECISION_FAILED",
                    "Agent returned an empty direct answer.",
                    502,
                )
            answer_text = answer_text.strip()
            decision_id = f"decision-{uuid4().hex}"
            if decision_recorder is not None:
                await decision_recorder(owner_id, decision_id, answer_text)
            return JSONResponse(
                DeskAgentDecisionResponse(
                    decision_id=decision_id,
                    decision_source="agent_generated_policy_approved",
                    mode="answer",
                    message="这个问题可以直接回答，不需要启动多步骤研究。",
                    routing_reason=routing_reason,
                    can_start=True,
                    answer_text=answer_text,
                    ui_actions=ui_actions,
                ).model_dump(mode="json"),
                status_code=200,
            )

        assert workflow_key is not None and definition is not None
        supported = worker_supports(definition)
        order_context_missing = (
            workflow_key is WorkflowKey.ORDER_REVIEW
            and payload.order_draft_id is None
        )
        can_start = (
            supported
            and not payload.active_workflow
            and not order_context_missing
        )
        if not supported:
            message = "该任务需要的执行服务尚未接通，因此不会创建一个注定失败的任务。"
        elif payload.active_workflow:
            message = "这个问题需要多步骤研究；当前已有任务执行中，本次不会重复创建。"
        elif order_context_missing:
            message = "订单草稿复核需要先在交易区创建一份当前草稿。"
        else:
            message = (
                f"这个问题需要启动“{definition.title}”工作流，"
                "因为结论依赖多个阶段的真实数据与证据复核。"
            )
        return JSONResponse(
            DeskAgentDecisionResponse(
                decision_id=f"decision-{uuid4().hex}",
                decision_source="agent_generated_policy_approved",
                mode="workflow",
                message=message,
                workflow_key=workflow_key.value,
                workflow_title=definition.title,
                routing_reason=routing_reason,
                expected_stages=definition.core_stages,
                can_start=can_start,
                ui_actions=ui_actions,
            ).model_dump(mode="json"),
            status_code=200,
        )

    async def preview_for_desk(request: Request) -> JSONResponse:
        try:
            await owner_resolver(request)
        except AuthenticationError as error:
            return _error("UNAUTHORIZED", str(error), 401)
        try:
            payload = DeskAgentDecisionRequest.model_validate(await request.json())
        except (ValidationError, ValueError) as error:
            return _error("AI_INVALID_REQUEST", str(error), 400)
        if _is_direct_answer(payload.message):
            return JSONResponse(
                DeskAgentPreviewResponse(
                    mode="answer",
                    expected_roles=("对话 Agent",),
                    artifact_types=("文字答复",),
                    can_start=True,
                ).model_dump(mode="json")
            )
        if workflow_definition_provider is None:
            return _error(
                "AI_RUNTIME_UNAVAILABLE",
                "The workflow registry is unavailable.",
                503,
            )
        workflow_key = select_desk_workflow(payload.message, section=payload.section)
        definition = workflow_definition_provider(workflow_key.value)
        roles = tuple(dict.fromkeys(
            agent_id
            for node in definition.nodes
            for agent_id in node.agent_ids
        ))
        order_context_missing = (
            workflow_key is WorkflowKey.ORDER_REVIEW
            and payload.order_draft_id is None
        )
        return JSONResponse(
            DeskAgentPreviewResponse(
                mode="workflow",
                workflow_key=workflow_key.value,
                workflow_title=definition.title,
                expected_roles=roles or ("系统服务",),
                artifact_types=(definition.final_artifact_type,),
                can_start=(
                    worker_supports(definition)
                    and not payload.active_workflow
                    and not order_context_missing
                ),
            ).model_dump(mode="json")
        )

    async def stream_desk_decision(request: Request) -> Response:
        try:
            owner_id = await owner_resolver(request)
        except AuthenticationError as error:
            return _error("UNAUTHORIZED", str(error), 401)
        try:
            payload = DeskAgentDecisionRequest.model_validate(await request.json())
        except (ValidationError, ValueError) as error:
            return _error("AI_INVALID_REQUEST", str(error), 400)
        if not _is_direct_answer(payload.message):
            return await decide_for_desk(request)
        try:
            runtime = await runtime_provider()
        except AgentRuntimeUnavailable as error:
            return _error("AI_RUNTIME_UNAVAILABLE", str(error), 503)
        try:
            profile_projection = await _load_profile_projection(
                profile_provider,
                owner_id,
            )
            portfolio_projection = await _load_portfolio_projection(
                portfolio_provider,
                owner_id,
            )
            turn, ui_actions = await _compose_turn_with_safe_ui_actions(
                runtime,
                payload=payload,
                workflow_title=None,
                profile_projection=profile_projection,
                portfolio_projection=portfolio_projection,
                include_answer=True,
            )
            routing_reason = str(turn.get("routing_reason", "")).strip()
            if not routing_reason:
                raise ValueError("Agent returned an empty routing reason")
            answer_text = turn.get("answer_text")
            if not isinstance(answer_text, str) or not answer_text.strip():
                raise ValueError("Agent returned an empty direct answer")
            answer_text = answer_text.strip()
        except Exception as error:  # noqa: BLE001 - model/policy boundary
            _LOGGER.exception("streaming desk turn Agent failed")
            return _error(
                "AI_DECISION_FAILED",
                f"Agent could not produce a valid desk turn: {type(error).__name__}",
                502,
            )

        decision_id = f"decision-{uuid4().hex}"
        start_payload = DeskAgentDecisionResponse(
            decision_id=decision_id,
            decision_source="agent_generated_policy_approved",
            mode="answer",
            message="这个问题可以直接回答，不需要启动多步骤研究。",
            routing_reason=routing_reason,
            can_start=True,
            answer_text=None,
            ui_actions=ui_actions,
        ).model_dump(mode="json")

        async def events() -> AsyncIterator[bytes]:
            yield (json.dumps({"type": "start", "decision": start_payload}, ensure_ascii=False) + "\n").encode()
            try:
                yield (json.dumps({"type": "delta", "text": answer_text}, ensure_ascii=False) + "\n").encode()
                if decision_recorder is not None:
                    await decision_recorder(owner_id, decision_id, answer_text)
                yield (json.dumps({"type": "done", "answer_text": answer_text}, ensure_ascii=False) + "\n").encode()
            except Exception as error:  # noqa: BLE001 - streaming boundary
                _LOGGER.exception("desk answer stream failed")
                yield (json.dumps({
                    "type": "error",
                    "code": "AI_STREAM_FAILED",
                    "message": f"Agent stream failed: {type(error).__name__}",
                }, ensure_ascii=False) + "\n").encode()

        return StreamingResponse(
            events(),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
        )

    return [
        Route("/research", research, methods=["POST"]),
        Route("/catalog", catalog, methods=["GET"]),
        Route("/desk/preview", preview_for_desk, methods=["POST"]),
        Route("/desk/decision", decide_for_desk, methods=["POST"]),
        Route("/desk/decision/stream", stream_desk_decision, methods=["POST"]),
    ]


def _is_direct_answer(message: str) -> bool:
    """Keep live-data and multi-step requests on durable workflows."""

    return not requires_desk_workflow(message)
