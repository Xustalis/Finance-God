"""Unified contracts shared by every VeriFolio agent."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator

from .models import EvidenceRecord


class ExecutionProfile(str, Enum):
    """Maximum side-effect class authorized for one run."""

    RESEARCH = "research"
    WORKSPACE = "workspace"
    EXTERNAL = "external"

    def allows(self, required: ExecutionProfile) -> bool:
        order = {
            ExecutionProfile.RESEARCH: 0,
            ExecutionProfile.WORKSPACE: 1,
            ExecutionProfile.EXTERNAL: 2,
        }
        return order[self] >= order[required]


class AgentAdapterKind(str, Enum):
    PROMPT = "prompt"
    DETERMINISTIC_MONITOR = "deterministic_monitor"
    FINROBOT_METRICS = "finrobot_metrics"


class AssetKind(str, Enum):
    EQUITY = "equity"
    FUND = "fund"
    PORTFOLIO = "portfolio"
    MARKET = "market"
    SOFTWARE = "software"
    OTHER = "other"


class ClaimKind(str, Enum):
    FACT = "fact"
    INFERENCE = "inference"


class AgentDefinition(BaseModel):
    """The single source of truth for one locally implemented agent."""

    agent_id: str = Field(pattern=r"^[A-Za-z0-9:_-]+$")
    title: str = Field(min_length=1, max_length=120)
    source: str = Field(min_length=1, max_length=48)
    description: str = Field(min_length=1, max_length=1_000)
    adapter: AgentAdapterKind
    minimum_profile: ExecutionProfile = ExecutionProfile.RESEARCH
    task_types: set[str] = Field(min_length=1)
    routing_tags: set[str] = Field(default_factory=set)
    asset_kinds: set[AssetKind] = Field(default_factory=set)
    required_resources: set[str] = Field(default_factory=set)
    external_actions: set[str] = Field(default_factory=set)
    authorization_by_task: dict[str, set[str]] = Field(default_factory=dict)
    auto_select: bool = False
    always_active: bool = False
    priority: int = Field(default=100, ge=0, le=1_000)
    source_path: str
    upstream_path: str
    license: str


class AgentRequest(BaseModel):
    """One routable request accepted by every agent adapter."""

    run_id: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9_-]+$")
    subject: str = Field(min_length=1, max_length=500)
    task_type: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
    profile: ExecutionProfile = ExecutionProfile.RESEARCH
    asset_kind: AssetKind = AssetKind.OTHER
    tags: set[str] = Field(default_factory=set, max_length=24)
    available_resources: set[str] = Field(default_factory=set, max_length=32)
    authorized_actions: set[str] = Field(default_factory=set, max_length=16)
    requested_agent_ids: list[str] = Field(default_factory=list, max_length=43)
    evidence: list[EvidenceRecord] = Field(default_factory=list, max_length=50)
    payload: dict[str, Any] = Field(default_factory=dict)
    max_agents: int = Field(default=8, ge=1, le=43)

    @model_validator(mode="after")
    def identifiers_must_be_unique(self) -> AgentRequest:
        evidence_ids = [item.identifier for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("evidence identifiers must be unique")
        if len(self.requested_agent_ids) != len(set(self.requested_agent_ids)):
            raise ValueError("requested_agent_ids must be unique")
        return self


class AgentAssignment(BaseModel):
    agent_id: str
    reason: str


class RoutingNotice(BaseModel):
    agent_id: str
    reason: str
    missing_resources: list[str] = Field(default_factory=list)
    missing_authorizations: list[str] = Field(default_factory=list)


class AgentPlan(BaseModel):
    run_id: str
    assignments: list[AgentAssignment] = Field(min_length=1)
    notices: list[RoutingNotice] = Field(default_factory=list)


class ClaimDraft(BaseModel):
    kind: ClaimKind
    statement: str = Field(min_length=1, max_length=2_000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=16)
    unknowns: list[str] = Field(default_factory=list, max_length=12)
    invalidation_conditions: list[str] = Field(default_factory=list, max_length=12)


class Claim(ClaimDraft):
    claim_id: str = Field(pattern=r"^[A-Za-z0-9:_-]+$")
    author_agent_id: str


class AgentArtifact(BaseModel):
    kind: str = Field(min_length=1, max_length=64)
    uri: str = Field(min_length=1, max_length=2_000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentResult(BaseModel):
    agent_id: str
    summary: str = Field(min_length=1, max_length=8_000)
    claims: list[Claim] = Field(default_factory=list, max_length=16)
    evidence: list[EvidenceRecord] = Field(default_factory=list, max_length=50)
    artifacts: list[AgentArtifact] = Field(default_factory=list, max_length=20)
    proposed_actions: list[str] = Field(default_factory=list, max_length=20)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentRun(BaseModel):
    run_id: str
    plan: AgentPlan
    results: list[AgentResult] = Field(min_length=1)


class AgentContext(BaseModel):
    request: AgentRequest
    evidence: list[EvidenceRecord]
    previous_results: list[AgentResult] = Field(default_factory=list)
