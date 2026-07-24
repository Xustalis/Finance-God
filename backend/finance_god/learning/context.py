"""Read-only access to verified learning context for product Agent requests."""

from __future__ import annotations

import re
import threading
from pathlib import Path

from pydantic import ValidationError
from research_runtime.models import EvidenceRecord

from .contracts import (
    KnowledgeSnapshot,
    Lesson,
    LessonValidationStatus,
)

_TOKEN = re.compile(r"[A-Za-z0-9_.-]{2,}|[\u4e00-\u9fff]{2,}")


class VerifiedKnowledgeReader:
    """Reload the atomic knowledge snapshot only when it changes."""

    def __init__(self, directory: Path) -> None:
        self._path = directory / "snapshot.json"
        self._lock = threading.Lock()
        self._mtime_ns: int | None = None
        self._verified: tuple[Lesson, ...] = ()

    def evidence(self, *, query: str, limit: int = 6) -> list[EvidenceRecord]:
        if limit <= 0:
            return []
        self._refresh()
        query_lower = query.lower()
        query_tokens = set(_TOKEN.findall(query_lower))

        def relevance(lesson: Lesson) -> tuple[int, float]:
            fields = [
                lesson.topic,
                lesson.statement,
                *lesson.tags,
                str(lesson.metadata.get("symbol", "")),
            ]
            searchable = " ".join(fields).lower()
            token_score = sum(token in searchable for token in query_tokens)
            tag_score = sum(tag.lower() in query_lower for tag in lesson.tags)
            return token_score + tag_score * 2, lesson.created_at.timestamp()

        ranked = [
            lesson
            for lesson in sorted(self._verified, key=relevance, reverse=True)
            if relevance(lesson)[0] > 0
        ]
        return [lesson.as_evidence() for lesson in ranked[:limit]]

    def _refresh(self) -> None:
        try:
            stat = self._path.stat()
        except FileNotFoundError:
            with self._lock:
                self._mtime_ns = None
                self._verified = ()
            return
        with self._lock:
            if self._mtime_ns == stat.st_mtime_ns:
                return
            try:
                snapshot = KnowledgeSnapshot.model_validate_json(
                    self._path.read_text(encoding="utf-8")
                )
            except (OSError, ValidationError) as error:
                raise RuntimeError(
                    f"verified knowledge snapshot is unreadable: {self._path}"
                ) from error
            self._verified = tuple(
                lesson
                for lesson in snapshot.recent
                if lesson.validation_status is LessonValidationStatus.VERIFIED
            )
            self._mtime_ns = stat.st_mtime_ns


__all__ = ["VerifiedKnowledgeReader"]
