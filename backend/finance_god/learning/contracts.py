"""Contracts for the continuous self-iteration learning loop.

The learning loop observes markets and backtests, asks the *current* agent
runtime to reason over that evidence, distills the agent's evidence-bound
claims into durable ``Lesson`` records, and feeds those lessons back as
evidence on the next cycle.  Everything here is intentionally decoupled from
concrete infrastructure through ``Protocol`` ports so the loop can be exercised
with offline doubles and wired to the real ARK runtime in production.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field
from research_runtime import AgentRun
from research_runtime.models import EvidenceRecord

_LESSON_TOPIC_MARKET = "market_learning"
_LESSON_TOPIC_BACKTEST = "backtest_scoring"
_LESSON_TOPIC_STRATEGY = "strategy_backtest"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class RealizedOutcome(BaseModel):
    """The known future outcome for a backtest case (scorer stage only)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    direction: str = Field(min_length=1, max_length=16)
    total_return: float
    horizon_end: str = Field(min_length=1, max_length=32)


class VerifiedResult(BaseModel):
    """A deterministic result that can safely become shared Agent knowledge."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    statement: str = Field(min_length=1, max_length=4_000)
    validation_method: str = Field(min_length=1, max_length=64)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Observation(BaseModel):
    """One evidence-shaped signal gathered at the start of a cycle."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    identifier: str = Field(min_length=1, max_length=64)
    source: str = Field(min_length=1, max_length=256)
    excerpt: str = Field(min_length=1, max_length=4_000)
    topic: str = Field(min_length=1, max_length=64)
    degraded: bool = False
    realized_outcome: RealizedOutcome | None = None
    verified_result: VerifiedResult | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_evidence(self) -> EvidenceRecord:
        return EvidenceRecord(
            identifier=self.identifier,
            source=self.source,
            excerpt=self.excerpt,
        )


class LessonValidationStatus(str, Enum):
    CANDIDATE = "candidate"
    VERIFIED = "verified"


class Lesson(BaseModel):
    """A durable, evidence-bound conclusion accumulated across cycles."""

    model_config = ConfigDict(extra="forbid")

    lesson_id: str = Field(min_length=1, max_length=96)
    created_at: datetime = Field(default_factory=_now)
    cycle: int = Field(ge=0)
    topic: str = Field(min_length=1, max_length=64)
    kind: str = Field(min_length=1, max_length=24)
    statement: str = Field(min_length=1, max_length=4_000)
    evidence_ids: list[str] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)
    source_run_id: str = Field(min_length=1, max_length=96)
    source_agent_id: str | None = None
    validation_status: LessonValidationStatus = LessonValidationStatus.CANDIDATE
    validation_method: str | None = Field(default=None, max_length=64)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def as_evidence(self) -> EvidenceRecord:
        """Render the lesson as prior-knowledge evidence for the next cycle."""

        provenance = self.source_agent_id or "synthesized"
        conditions = (
            f" 失效条件：{'；'.join(self.invalidation_conditions)}"
            if self.invalidation_conditions
            else ""
        )
        excerpt = (
            f"[{self.validation_status.value}:{self.kind}] "
            f"{self.statement}{conditions}"
        )
        return EvidenceRecord(
            identifier=self.lesson_id,
            source=f"learning:{self.topic}:{provenance}",
            excerpt=excerpt[:4_000],
        )


class KnowledgeSnapshot(BaseModel):
    """A point-in-time summary of the accumulated knowledge base."""

    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=0)
    updated_at: datetime = Field(default_factory=_now)
    total_lessons: int = Field(ge=0)
    topics: dict[str, int] = Field(default_factory=dict)
    recent: list[Lesson] = Field(default_factory=list)


class CycleReport(BaseModel):
    """An auditable record of one learning cycle."""

    model_config = ConfigDict(extra="forbid")

    cycle: int = Field(ge=0)
    topic: str
    run_id: str
    status: str = Field(default="ok")
    started_at: datetime = Field(default_factory=_now)
    finished_at: datetime | None = None
    observation_ids: list[str] = Field(default_factory=list)
    prior_lesson_ids: list[str] = Field(default_factory=list)
    new_lesson_ids: list[str] = Field(default_factory=list)
    agent_ids: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class LearningConfig(BaseModel):
    """Runtime configuration for the continuous learning loop."""

    model_config = ConfigDict(extra="forbid")

    knowledge_dir: Path
    interval_seconds: float = Field(default=900.0, gt=0)
    symbols: tuple[str, ...] = Field(
        default=("000300.SH",),
        min_length=1,
        max_length=16,
    )
    market_bar_limit: int = Field(default=120, ge=40, le=500)
    max_prior_lessons: int = Field(default=12, ge=0, le=40)
    max_observations: int = Field(default=20, ge=1, le=48)
    max_agents: int = Field(default=6, ge=1, le=44)
    run_id_prefix: str = Field(default="learn", pattern=r"^[A-Za-z0-9_-]+$")
    enable_market: bool = True
    enable_backtest: bool = True
    strategy_transaction_cost_bps: float = Field(default=10.0, ge=0, le=100)

    @classmethod
    def from_environment(cls) -> "LearningConfig":
        workspace_root = Path(__file__).resolve().parents[3]
        knowledge_dir = Path(
            os.getenv(
                "FINANCE_GOD_KNOWLEDGE_DIR",
                str(workspace_root / "artifacts" / "knowledge"),
            )
        )
        symbols_env = os.getenv("FINANCE_GOD_LEARNING_SYMBOLS")
        symbols = (
            tuple(s.strip() for s in symbols_env.split(",") if s.strip())
            if symbols_env
            else cls.model_fields["symbols"].default
        )
        return cls(
            knowledge_dir=knowledge_dir,
            interval_seconds=float(
                os.getenv("FINANCE_GOD_LEARNING_INTERVAL_SECONDS", "900")
            ),
            symbols=symbols,
            enable_market=os.getenv("FINANCE_GOD_LEARNING_MARKET", "1") != "0",
            enable_backtest=os.getenv("FINANCE_GOD_LEARNING_BACKTEST", "1") != "0",
            strategy_transaction_cost_bps=float(
                os.getenv("FINANCE_GOD_LEARNING_TRANSACTION_COST_BPS", "10")
            ),
        )


@runtime_checkable
class ObservationSource(Protocol):
    """Gathers evidence-shaped observations for a given cycle."""

    topic: str

    async def observe(self, cycle: int) -> list[Observation]:
        ...


@runtime_checkable
class KnowledgeStore(Protocol):
    """Durable store for accumulated lessons and cycle audit trail."""

    def recent_lessons(
        self,
        *,
        limit: int,
        topic: str | None = None,
        verified_only: bool = False,
    ) -> list[Lesson]:
        ...

    def prior_evidence(
        self,
        *,
        limit: int,
        topic: str | None = None,
        verified_only: bool = True,
    ) -> list[EvidenceRecord]:
        ...

    def seen_observation(self, identifier: str) -> bool:
        ...

    def record_lessons(self, lessons: list[Lesson]) -> None:
        ...

    def record_cycle(self, report: CycleReport) -> None:
        ...

    def write_snapshot(self, *, recent_limit: int = 20) -> KnowledgeSnapshot:
        ...


@runtime_checkable
class AgentGateway(Protocol):
    """Bridges the learning loop to the current multi-agent runtime."""

    async def reason(
        self,
        *,
        run_id: str,
        subject: str,
        task_type: str,
        evidence: list[EvidenceRecord],
        max_agents: int,
    ) -> AgentRun:
        ...


__all__ = [
    "AgentGateway",
    "CycleReport",
    "KnowledgeSnapshot",
    "KnowledgeStore",
    "LearningConfig",
    "Lesson",
    "LessonValidationStatus",
    "Observation",
    "ObservationSource",
    "RealizedOutcome",
    "VerifiedResult",
    "_LESSON_TOPIC_BACKTEST",
    "_LESSON_TOPIC_MARKET",
    "_LESSON_TOPIC_STRATEGY",
]
