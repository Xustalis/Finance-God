"""Read-only projection of the continuous-learning worker's durable artifacts."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

LearningSummaryStatus = Literal["healthy", "stale", "unavailable", "error"]


class _ArtifactModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _LessonArtifact(_ArtifactModel):
    lesson_id: str
    created_at: datetime
    cycle: int = Field(ge=0)
    topic: str
    statement: str
    invalidation_conditions: list[str] = Field(default_factory=list)
    validation_status: str
    validation_method: str | None = None
    tags: list[str] = Field(default_factory=list)


class _SnapshotArtifact(_ArtifactModel):
    version: int = Field(ge=0)
    updated_at: datetime
    total_lessons: int = Field(ge=0)
    topics: dict[str, int] = Field(default_factory=dict)
    recent: list[_LessonArtifact] = Field(default_factory=list)


class _CycleArtifact(_ArtifactModel):
    cycle: int = Field(ge=0)
    topic: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    notes: list[str] = Field(default_factory=list)


class LearningCycleSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    cycle: int
    topic: str
    status: str
    started_at: datetime
    completed_at: datetime | None
    summary: str | None


class LearningSnapshotSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: int
    total_lessons: int
    topics: dict[str, int]
    updated_at: datetime


class VerifiedLessonSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    lesson_id: str
    statement: str
    topic: str
    validation_method: str | None
    cycle: int
    created_at: datetime
    tags: list[str]
    invalidation_conditions: list[str]


class LearningFreshness(BaseModel):
    model_config = ConfigDict(frozen=True)

    configured_interval_seconds: float
    age_seconds: float | None
    is_stale: bool


class AgentLearningSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: LearningSummaryStatus
    message: str | None = None
    last_cycle: LearningCycleSummary | None = None
    snapshot: LearningSnapshotSummary | None = None
    recent_verified_lessons: list[VerifiedLessonSummary] = Field(default_factory=list)
    freshness: LearningFreshness


class AgentLearningSummaryReader:
    """Read the worker's atomic snapshot and cycle audit without mutating them."""

    def __init__(
        self,
        knowledge_dir: Path,
        *,
        interval_seconds: float = 900.0,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be greater than zero")
        self._knowledge_dir = knowledge_dir
        self._interval_seconds = interval_seconds
        self._now = now or (lambda: datetime.now(UTC))

    @classmethod
    def from_environment(cls) -> "AgentLearningSummaryReader":
        workspace_root = Path(__file__).resolve().parents[3]
        return cls(
            Path(
                os.getenv(
                    "FINANCE_GOD_KNOWLEDGE_DIR",
                    str(workspace_root / "artifacts" / "knowledge"),
                )
            ),
            interval_seconds=float(
                os.getenv("FINANCE_GOD_LEARNING_INTERVAL_SECONDS", "900")
            ),
        )

    def read(self) -> AgentLearningSummary:
        snapshot_path = self._knowledge_dir / "snapshot.json"
        empty_freshness = LearningFreshness(
            configured_interval_seconds=self._interval_seconds,
            age_seconds=None,
            is_stale=False,
        )
        try:
            cycle_paths = sorted(
                (self._knowledge_dir / "cycles").glob("cycle-*.json"), reverse=True
            )
        except OSError as error:
            return AgentLearningSummary(
                status="error",
                message=f"持续学习产物无法读取：{type(error).__name__}",
                freshness=empty_freshness,
            )
        if not snapshot_path.exists() and not cycle_paths:
            return AgentLearningSummary(
                status="unavailable",
                message="持续学习尚未完成首个周期。",
                freshness=empty_freshness,
            )

        try:
            snapshot = (
                _SnapshotArtifact.model_validate_json(
                    snapshot_path.read_text(encoding="utf-8")
                )
                if snapshot_path.exists()
                else None
            )
            recent_cycles = [
                _CycleArtifact.model_validate_json(path.read_text(encoding="utf-8"))
                for path in cycle_paths[:3]
            ]
        except (OSError, UnicodeError, ValidationError, json.JSONDecodeError) as error:
            return AgentLearningSummary(
                status="error",
                message=f"持续学习产物无法读取：{type(error).__name__}",
                freshness=empty_freshness,
            )

        last_cycle = recent_cycles[0] if recent_cycles else None
        completed_at = last_cycle.finished_at if last_cycle is not None else None
        age_seconds = (
            max(0.0, (self._utc_now() - completed_at.astimezone(UTC)).total_seconds())
            if completed_at is not None
            else None
        )
        stale = (
            age_seconds is not None
            and age_seconds > max(self._interval_seconds * 4, 300.0)
        )
        freshness = LearningFreshness(
            configured_interval_seconds=self._interval_seconds,
            age_seconds=age_seconds,
            is_stale=stale,
        )
        cycle_summary = (
            LearningCycleSummary(
                cycle=last_cycle.cycle,
                topic=last_cycle.topic,
                status=last_cycle.status,
                started_at=last_cycle.started_at,
                completed_at=last_cycle.finished_at,
                summary="；".join(last_cycle.notes) or None,
            )
            if last_cycle is not None
            else None
        )
        snapshot_summary = (
            LearningSnapshotSummary(
                version=snapshot.version,
                total_lessons=snapshot.total_lessons,
                topics=dict(snapshot.topics),
                updated_at=snapshot.updated_at,
            )
            if snapshot is not None
            else None
        )
        lessons = (
            [
                VerifiedLessonSummary(
                    lesson_id=lesson.lesson_id,
                    statement=lesson.statement,
                    topic=lesson.topic,
                    validation_method=lesson.validation_method,
                    cycle=lesson.cycle,
                    created_at=lesson.created_at,
                    tags=list(lesson.tags),
                    invalidation_conditions=list(lesson.invalidation_conditions),
                )
                for lesson in sorted(
                    (
                        item
                        for item in snapshot.recent
                        if item.validation_status == "verified"
                    ),
                    key=lambda item: item.created_at,
                    reverse=True,
                )[:5]
            ]
            if snapshot is not None
            else []
        )

        if len(recent_cycles) >= 3 and all(
            cycle.status == "error" for cycle in recent_cycles
        ):
            status: LearningSummaryStatus = "error"
            message = "持续学习最近三个周期均运行失败。"
        elif last_cycle is None or last_cycle.finished_at is None:
            status = "unavailable"
            message = "持续学习尚未完成首个周期。"
        elif stale:
            status = "stale"
            message = "最近学习周期已超过允许的数据时效。"
        else:
            status = "healthy"
            message = None
        return AgentLearningSummary(
            status=status,
            message=message,
            last_cycle=cycle_summary,
            snapshot=snapshot_summary,
            recent_verified_lessons=lessons,
            freshness=freshness,
        )

    def _utc_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            raise ValueError("now must return a timezone-aware datetime")
        return value.astimezone(UTC)


__all__ = [
    "AgentLearningSummary",
    "AgentLearningSummaryReader",
    "LearningCycleSummary",
    "LearningFreshness",
    "LearningSnapshotSummary",
    "VerifiedLessonSummary",
]
