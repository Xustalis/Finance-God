from __future__ import annotations

import asyncio
from pathlib import Path

from research_runtime.contracts import (
    AgentAssignment,
    AgentPlan,
    AgentResult,
    AgentRun,
)

from finance_god.learning.context import VerifiedKnowledgeReader
from finance_god.learning.contracts import (
    CycleReport,
    LearningConfig,
    Lesson,
    LessonValidationStatus,
    Observation,
)
from finance_god.learning.knowledge_store import JsonKnowledgeStore
from finance_god.learning.loop import ContinuousLearningLoop


def _lesson(
    lesson_id: str,
    status: LessonValidationStatus,
) -> Lesson:
    return Lesson(
        lesson_id=lesson_id,
        cycle=0,
        topic="market_learning",
        kind="outcome",
        statement=f"{status.value} statement",
        evidence_ids=["OBS-1"],
        source_run_id="run-1",
        validation_status=status,
        tags=["510300.SH"],
    )


def test_store_and_reader_expose_only_verified_lessons(tmp_path: Path) -> None:
    store = JsonKnowledgeStore(tmp_path)
    store.record_lessons(
        [
            _lesson("L-CANDIDATE", LessonValidationStatus.CANDIDATE),
            _lesson("L-VERIFIED", LessonValidationStatus.VERIFIED),
        ]
    )
    store.write_snapshot()

    prior = store.prior_evidence(limit=10, topic="market_learning")
    product = VerifiedKnowledgeReader(tmp_path).evidence(
        query="510300.SH",
        limit=10,
    )
    unrelated = VerifiedKnowledgeReader(tmp_path).evidence(
        query="600519.SH",
        limit=10,
    )

    assert [item.identifier for item in prior] == ["L-VERIFIED"]
    assert [item.identifier for item in product] == ["L-VERIFIED"]
    assert unrelated == []


def test_cycle_observations_are_restored_for_duplicate_suppression(
    tmp_path: Path,
) -> None:
    store = JsonKnowledgeStore(tmp_path)
    store.record_cycle(
        CycleReport(
            cycle=4,
            topic="market_learning",
            run_id="learn-mkt-000004",
            observation_ids=["OBS-4"],
        )
    )

    restored = JsonKnowledgeStore(tmp_path)

    assert restored.seen_observation("OBS-4") is True
    assert restored.next_cycle_index() == 5


def test_failed_cycle_does_not_suppress_observation_retry(tmp_path: Path) -> None:
    store = JsonKnowledgeStore(tmp_path)
    store.record_cycle(
        CycleReport(
            cycle=4,
            topic="market_learning",
            run_id="learn-mkt-000004",
            status="error",
            observation_ids=["OBS-FAILED"],
        )
    )

    assert store.seen_observation("OBS-FAILED") is False
    assert JsonKnowledgeStore(tmp_path).seen_observation("OBS-FAILED") is False


def test_loop_skips_unchanged_observation_without_second_agent_call(
    tmp_path: Path,
) -> None:
    class Source:
        topic = "market_learning"

        async def observe(self, cycle: int):
            del cycle
            return [
                Observation(
                    identifier="OBS-STABLE",
                    source="test",
                    excerpt="same data",
                    topic=self.topic,
                )
            ]

    class Gateway:
        calls = 0

        async def reason(self, **kwargs):
            self.calls += 1
            run_id = kwargs["run_id"]
            return AgentRun(
                run_id=run_id,
                plan=AgentPlan(
                    run_id=run_id,
                    assignments=[AgentAssignment(agent_id="market", reason="test")],
                ),
                results=[AgentResult(agent_id="market", summary="no claims")],
            )

    store = JsonKnowledgeStore(tmp_path)
    gateway = Gateway()
    loop = ContinuousLearningLoop(
        config=LearningConfig(knowledge_dir=tmp_path),
        store=store,
        sources=[Source()],
        gateway=gateway,
    )

    first = asyncio.run(loop.run_cycle(0))
    second = asyncio.run(loop.run_cycle(1))

    assert first.status == "ok"
    assert second.status == "skipped"
    assert gateway.calls == 1
