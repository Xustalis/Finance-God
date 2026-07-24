"""HTTP surface for the unified Multi-Agent research runtime.

These routes expose the orchestration runtime as an on-demand research
capability. They never fabricate AI output: when the runtime is not
configured or an execution fails, the caller receives an explicit error so
the frontend can render a visible failure state instead of a default answer.
"""

from __future__ import annotations

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

from finance_god.api.auth import AuthenticationError

OwnerResolver = Callable[[Request], str]


class AgentRuntimeUnavailable(RuntimeError):
    """Raised when the Multi-Agent runtime cannot be configured."""


class _AgentRuntime(Protocol):  # pragma: no cover - typing helper only
    async def run(self, request: AgentRequest) -> AgentRun: ...

    def list_agents(self) -> tuple: ...


RuntimeProvider = Callable[[], Awaitable["_AgentRuntime"]]


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


def create_agent_routes(
    *,
    runtime_provider: RuntimeProvider,
    owner_resolver: OwnerResolver,
) -> list[Route]:
    """Build the ``/agent/*`` routes bound to a lazy runtime provider."""

    async def research(request: Request) -> JSONResponse:
        try:
            owner_resolver(request)
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
        agent_request = AgentRequest(
            run_id=f"fg-{uuid4().hex}",
            subject=payload.subject,
            task_type=payload.task_type,
            asset_kind=payload.asset_kind,
            evidence=[
                EvidenceRecord(
                    identifier=item.identifier,
                    source=item.source,
                    excerpt=item.excerpt,
                )
                for item in payload.evidence
            ],
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
        return JSONResponse(run.model_dump(mode="json"), status_code=200)

    async def catalog(request: Request) -> JSONResponse:
        try:
            owner_resolver(request)
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
