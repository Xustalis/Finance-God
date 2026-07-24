"""Adapters that execute every agent through the unified result envelope."""

from __future__ import annotations

import json
from typing import Protocol

from pydantic import BaseModel, Field, ValidationError

from .config import FmpSettings
from .contracts import (
    AgentAdapterKind,
    AgentArtifact,
    AgentContext,
    AgentDefinition,
    AgentResult,
    Claim,
    ClaimDraft,
)
from .data_provider import DataProvider, PandaDataEvidenceCompiler
from .finrobot_adapter import _FinRobotMetricsProcess, _FinRobotMetricsRequest
from .llm import ChatClient
from .models import EvidenceRecord, PandaMonitorKind, PandaMonitorRequest
from .monitors import analyze_monitor, build_monitor_queries


class AgentAdapter(Protocol):
    def run(self, definition: AgentDefinition, context: AgentContext) -> AgentResult: ...


class AgentDependencyError(RuntimeError):
    """Raised when an adapter dependency was not injected into the runner."""


class _PromptPayload(BaseModel):
    summary: str = Field(min_length=1, max_length=8_000)
    claims: list[ClaimDraft] = Field(default_factory=list, max_length=16)
    proposed_actions: list[str] = Field(default_factory=list, max_length=20)


class StructuredPromptAdapter:
    """Run one role with strict JSON and evidence-reference validation."""

    def __init__(self, client: ChatClient) -> None:
        self._client = client

    def run(self, definition: AgentDefinition, context: AgentContext) -> AgentResult:
        if not context.evidence:
            raise ValueError(
                f"{definition.agent_id} requires at least one evidence record"
            )
        raw = self._client.complete(
            system_prompt=self._system_prompt(definition),
            user_prompt=self._user_prompt(definition, context),
        )
        try:
            payload = _PromptPayload.model_validate_json(raw)
        except ValidationError as error:
            raise ValueError(
                f"invalid structured response from {definition.agent_id}: {error}"
            ) from error
        if context.request.task_type == "research" and not payload.claims:
            raise ValueError(
                f"{definition.agent_id} must return at least one claim for research"
            )
        available_evidence = {item.identifier for item in context.evidence}
        claims = []
        for index, draft in enumerate(payload.claims, start=1):
            if context.request.task_type == "research" and not draft.evidence_ids:
                raise ValueError(
                    f"{definition.agent_id} research claims require evidence_ids"
                )
            unknown_ids = sorted(set(draft.evidence_ids) - available_evidence)
            if unknown_ids:
                raise ValueError(
                    f"{definition.agent_id} referenced unavailable evidence: {unknown_ids}"
                )
            claims.append(
                Claim(
                    **draft.model_dump(),
                    claim_id=f"{definition.agent_id}:claim-{index}",
                    author_agent_id=definition.agent_id,
                )
            )
        return AgentResult(
            agent_id=definition.agent_id,
            summary=payload.summary,
            claims=claims,
            proposed_actions=payload.proposed_actions,
        )

    @staticmethod
    def _system_prompt(definition: AgentDefinition) -> str:
        return f"""You are {definition.title}, implemented in the VeriFolio unified agent runtime.
Mission: {definition.description}
Your maximum authorized execution profile is declared by the caller. Do not claim that a file,
command, publication, service, account, or transaction changed unless an adapter result explicitly
shows that change. Return only valid JSON matching the requested schema."""

    @staticmethod
    def _user_prompt(definition: AgentDefinition, context: AgentContext) -> str:
        evidence = "\n".join(
            f"[{item.identifier}] {item.source}: {item.excerpt}" for item in context.evidence
        ) or "No evidence records were supplied."
        previous = json.dumps(
            [
                {
                    "agent_id": result.agent_id,
                    "summary": result.summary,
                    "claims": [claim.model_dump(mode="json") for claim in result.claims],
                }
                for result in context.previous_results
            ],
            ensure_ascii=False,
        )
        return f"""Task type: {context.request.task_type}
Subject: {context.request.subject}
Agent: {definition.agent_id}
Tags: {sorted(context.request.tags)}
Payload: {json.dumps(context.request.payload, ensure_ascii=False, default=str)}

Evidence:
{evidence}

Previous agent results:
{previous}

Return JSON with this exact top-level shape:
{{"summary":"string","claims":[{{"kind":"fact|inference","statement":"string",
"evidence_ids":["E1"],"unknowns":["string"],"invalidation_conditions":["string"]}}],
"proposed_actions":["string"]}}

Claims may be empty when this role is producing a task plan or an artifact-oriented report.
Every non-empty evidence_ids value must reference an identifier shown above. proposed_actions are
reviewable requests only; never state that they were executed."""


_MONITOR_AGENT_KINDS = {
    "quantskills:agent-correlation-break-research": PandaMonitorKind.CORRELATION_BREAK,
    "quantskills:agent-crowding-risk-monitor": PandaMonitorKind.CROWDING_RISK,
    "quantskills:agent-derivatives-skew-sentiment-monitor": (
        PandaMonitorKind.DERIVATIVES_IV_PREMIUM
    ),
    "quantskills:agent-market-regime-monitor": PandaMonitorKind.MARKET_REGIME,
}


class DeterministicMonitorAdapter:
    def __init__(
        self,
        provider: DataProvider,
        compiler: PandaDataEvidenceCompiler | None = None,
    ) -> None:
        self._provider = provider
        self._compiler = compiler or PandaDataEvidenceCompiler()

    def run(self, definition: AgentDefinition, context: AgentContext) -> AgentResult:
        expected_kind = _MONITOR_AGENT_KINDS[definition.agent_id]
        supplied_kind = context.request.payload.get("kind")
        if supplied_kind != expected_kind.value:
            raise ValueError(
                f"{definition.agent_id} requires monitor kind {expected_kind.value}, "
                f"received {supplied_kind}"
            )
        request = PandaMonitorRequest.model_validate(context.request.payload)
        artifacts = [self._provider.fetch(query) for query in build_monitor_queries(request)]
        snapshot = analyze_monitor(request, artifacts)
        evidence = [self._compiler.compile(artifact) for artifact in artifacts]
        snapshot_evidence = EvidenceRecord(
            identifier=f"monitor-{request.kind.value}",
            source=f"deterministic {definition.agent_id}",
            excerpt=(
                f"state={snapshot.state}; confidence={snapshot.confidence}; "
                f"metrics={json.dumps(snapshot.metrics, ensure_ascii=False, sort_keys=True)}; "
                f"limitations={json.dumps(snapshot.limitations, ensure_ascii=False)}"
            ),
        )
        evidence.append(snapshot_evidence)
        claim = Claim(
            claim_id=f"{definition.agent_id}:claim-1",
            author_agent_id=definition.agent_id,
            kind="inference",
            statement=f"{snapshot.state} ({snapshot.confidence} confidence)",
            evidence_ids=[item.identifier for item in evidence],
            unknowns=snapshot.limitations,
        )
        serialized_artifacts = [
            AgentArtifact(
                kind="pandadata_query",
                uri=f"pandadata://{artifact.query.dataset.value}/{artifact.query.identifier}",
                metadata=artifact.model_dump(mode="json"),
            )
            for artifact in artifacts
        ]
        return AgentResult(
            agent_id=definition.agent_id,
            summary=snapshot_evidence.excerpt,
            claims=[claim],
            evidence=evidence,
            artifacts=serialized_artifacts,
            metadata={"snapshot": snapshot.model_dump(mode="json")},
        )


class FinRobotMetricsAdapter:
    def __init__(self, settings: FmpSettings) -> None:
        self._runner = _FinRobotMetricsProcess(settings)

    def run(self, definition: AgentDefinition, context: AgentContext) -> AgentResult:
        request = _FinRobotMetricsRequest(**context.request.payload)
        result = self._runner.run(request)
        artifacts = [
            AgentArtifact(
                kind="finrobot_metric",
                uri=f"{result.output_dir}/{path}",
                metadata={"run_id": result.run_id, "ticker": result.ticker},
            )
            for path in result.files
        ]
        return AgentResult(
            agent_id=definition.agent_id,
            summary=(
                f"Generated {len(artifacts)} deterministic FinRobot metric artifact(s) "
                f"for {result.ticker}."
            ),
            artifacts=artifacts,
            metadata=result.model_dump(),
        )


class AdapterResolver:
    def __init__(
        self,
        *,
        chat_client: ChatClient | None = None,
        data_provider: DataProvider | None = None,
        fmp_settings: FmpSettings | None = None,
    ) -> None:
        self._prompt = StructuredPromptAdapter(chat_client) if chat_client else None
        self._monitor = DeterministicMonitorAdapter(data_provider) if data_provider else None
        self._finrobot = FinRobotMetricsAdapter(fmp_settings) if fmp_settings else None

    def resolve(self, definition: AgentDefinition) -> AgentAdapter:
        if definition.adapter == AgentAdapterKind.PROMPT:
            if self._prompt is None:
                raise AgentDependencyError("prompt agents require a ChatClient")
            return self._prompt
        if definition.adapter == AgentAdapterKind.DETERMINISTIC_MONITOR:
            if self._monitor is None:
                raise AgentDependencyError("monitor agents require a DataProvider")
            return self._monitor
        if self._finrobot is None:
            raise AgentDependencyError("FinRobot metrics require FmpSettings")
        return self._finrobot
