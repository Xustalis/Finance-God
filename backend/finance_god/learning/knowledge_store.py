"""JSON-backed knowledge store for the continuous learning loop.

Lessons are appended to ``lessons.jsonl`` (immutable audit log), a compact
``snapshot.json`` mirrors the most recent knowledge state, and every cycle is
recorded under ``cycles/``.  The store is deliberately dependency-free so the
knowledge base is diffable, inspectable, and safe to seed before a database is
introduced.
"""

from __future__ import annotations

import threading
from pathlib import Path

from research_runtime.models import EvidenceRecord

from .contracts import (
    CycleReport,
    KnowledgeSnapshot,
    Lesson,
    LessonValidationStatus,
)


class JsonKnowledgeStore:
    """File-backed implementation of the ``KnowledgeStore`` protocol."""

    def __init__(self, directory: Path) -> None:
        self._dir = directory
        self._lessons_path = directory / "lessons.jsonl"
        self._snapshot_path = directory / "snapshot.json"
        self._cycles_dir = directory / "cycles"
        self._lock = threading.Lock()
        self._lessons: list[Lesson] = []
        self._lesson_ids: set[str] = set()
        self._processed_observation_ids: set[str] = set()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._cycles_dir.mkdir(parents=True, exist_ok=True)
        self._load()
        self._load_cycles()

    def _load(self) -> None:
        if not self._lessons_path.exists():
            return
        for line in self._lessons_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            lesson = Lesson.model_validate_json(stripped)
            self._lessons.append(lesson)
            self._lesson_ids.add(lesson.lesson_id)

    def _load_cycles(self) -> None:
        for path in self._cycles_dir.glob("cycle-*.json"):
            report = CycleReport.model_validate_json(path.read_text(encoding="utf-8"))
            if report.status == "ok":
                self._processed_observation_ids.update(report.observation_ids)

    def recent_lessons(
        self,
        *,
        limit: int,
        topic: str | None = None,
        verified_only: bool = False,
    ) -> list[Lesson]:
        with self._lock:
            pool = [
                lesson
                for lesson in self._lessons
                if (topic is None or lesson.topic == topic)
                and (
                    not verified_only
                    or lesson.validation_status is LessonValidationStatus.VERIFIED
                )
            ]
        if limit <= 0:
            return []
        return pool[-limit:]

    def prior_evidence(
        self,
        *,
        limit: int,
        topic: str | None = None,
        verified_only: bool = True,
    ) -> list[EvidenceRecord]:
        return [
            lesson.as_evidence()
            for lesson in self.recent_lessons(
                limit=limit,
                topic=topic,
                verified_only=verified_only,
            )
        ]

    def seen_observation(self, identifier: str) -> bool:
        with self._lock:
            return identifier in self._processed_observation_ids

    def record_lessons(self, lessons: list[Lesson]) -> None:
        if not lessons:
            return
        with self._lock:
            new_lessons = [
                lesson for lesson in lessons if lesson.lesson_id not in self._lesson_ids
            ]
            if not new_lessons:
                return
            with self._lessons_path.open("a", encoding="utf-8") as handle:
                for lesson in new_lessons:
                    handle.write(lesson.model_dump_json() + "\n")
                handle.flush()
            self._lessons.extend(new_lessons)
            self._lesson_ids.update(lesson.lesson_id for lesson in new_lessons)

    def record_cycle(self, report: CycleReport) -> None:
        path = self._cycles_dir / f"cycle-{report.cycle:06d}.json"
        self._atomic_write(path, report.model_dump_json(indent=2))
        if report.status == "ok":
            with self._lock:
                self._processed_observation_ids.update(report.observation_ids)

    def next_cycle_index(self) -> int:
        """Resume numbering after the highest recorded cycle to avoid id clashes."""

        highest = -1
        for path in self._cycles_dir.glob("cycle-*.json"):
            try:
                highest = max(highest, int(path.stem.split("-")[-1]))
            except ValueError:
                continue
        return highest + 1

    def write_snapshot(self, *, recent_limit: int = 100) -> KnowledgeSnapshot:
        with self._lock:
            topics: dict[str, int] = {}
            for lesson in self._lessons:
                topics[lesson.topic] = topics.get(lesson.topic, 0) + 1
            snapshot = KnowledgeSnapshot(
                version=len(self._lessons),
                total_lessons=len(self._lessons),
                topics=topics,
                recent=self._lessons[-recent_limit:] if recent_limit > 0 else [],
            )
        self._atomic_write(
            self._snapshot_path,
            snapshot.model_dump_json(indent=2),
        )
        return snapshot

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)

    @property
    def total_lessons(self) -> int:
        with self._lock:
            return len(self._lessons)


__all__ = ["JsonKnowledgeStore"]
