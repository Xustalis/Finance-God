"""HTTP surface for the unified Multi-Agent research runtime.

These routes expose the orchestration runtime as an on-demand research
capability. They never fabricate AI output: when the runtime is not
configured or an execution fails, the caller receives an explicit error so
the frontend can render a visible failure state instead of a default answer.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from research_runtime import AgentRequest, AssetKind
from research_runtime.contracts import AgentRun
from research_runtime.models import EvidenceRecord
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from finance_god.api.auth import AuthenticationError, OwnerResolver


class AgentRuntimeUnavailable(RuntimeError):
    """Raised when the Multi-Agent runtime cannot be configured."""


class _AgentRuntime(Protocol):  # pragma: no cover - typing helper only
    async def run(self, request: AgentRequest) -> AgentRun: ...

    def list_agents(self) -> tuple: ...


RuntimeProvider = Callable[[], Awaitable["_AgentRuntime"]]
# (owner_id, subject, run) -> None; best-effort persistence of run evidence.
EvidenceRecorder = Callable[[str, str, AgentRun], Awaitable[None]]
# owner_id -> compact investor-profile context, or None when the caller has no
# completed profile. The value is injected as agent context so the planner and
# every prompt agent can tailor their reasoning to the user's mandate.
ProfileProvider = Callable[[str], Awaitable["dict | None"]]
LearningContextProvider = Callable[
    [str, str, str],
    Awaitable[list[EvidenceRecord]],
]

# Stable identifier for the synthetic evidence record carrying the profile so
# research claims can cite it and it never collides with caller-supplied ids.
_PROFILE_EVIDENCE_ID = "investor-profile"
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
    learning_context_provider: LearningContextProvider | None = None,
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
                profile = await profile_provider(owner_id)
            except Exception:  # noqa: BLE001 - profile context is best-effort
                profile = None
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
        # Inject crawler news and sentiment as baseline evidence so agents
        # like news_analyst and sentiment_analyst always have input data.
        try:
            from finance_god.crawler.service import CrawlerService
            _crawler = CrawlerService()
            news = await _crawler.get_news(limit=10)
            if news:
                news_text = "; ".join(
                    f"[{n.sector}] {n.title}" for n in news[:8]
                )
                contextual_evidence.append(
                    EvidenceRecord(
                        identifier="E1",
                        source="Finance-God Crawler (eastmoney real-time news)",
                        excerpt=f"Latest A-share market news: {news_text}",
                    )
                )
            sentiment = await _crawler.get_sentiment()
            contextual_evidence.append(
                EvidenceRecord(
                    identifier="E2",
                    source="Finance-God Crawler (eastmoney+ths sentiment)",
                    excerpt=(
                        f"Market sentiment score={sentiment.score}/100 "
                        f"level={sentiment.level.value}; "
                        f"north_flow={sentiment.north_flow}B CNY; "
                        f"up_ratio={sentiment.breadth.up_ratio}; "
                        f"hot_sectors={','.join(sentiment.hot_sectors[:5])}; "
                        f"risk_sectors={','.join(sentiment.risk_sectors[:5])}"
                    ),
                )
            )
        except Exception:  # noqa: BLE001 - crawler evidence is best-effort
            _LOGGER.warning("crawler evidence injection failed")
        evidence = _merge_evidence(evidence, contextual_evidence)
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
            return _error(
                "AI_RUNTIME_ERROR",
                "The research run failed. No conclusion was produced.",
                502,
            )
        if evidence_recorder is not None:
            try:
                await evidence_recorder(owner_id, payload.subject, run)
            except Exception:  # noqa: BLE001 - evidence capture must never break the run
                pass
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

    return [
        Route("/research", research, methods=["POST"]),
        Route("/catalog", catalog, methods=["GET"]),
    ]
