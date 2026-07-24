"""Distill agent runs into durable, evidence-bound lessons.

The synthesizer converts the *current* agent's structured claims into
``Lesson`` records and, for backtest cases whose realized outcome is known,
appends a deterministic ``outcome`` lesson that grounds the agent's thesis
against reality.  These lessons are what the loop feeds back as evidence, so
they must stay evidence-bound and free of fabricated numbers.
"""

from __future__ import annotations

import re

from research_runtime import AgentRun

from .contracts import (
    Lesson,
    LessonValidationStatus,
    Observation,
)

MAX_LESSONS_PER_CYCLE = 12
_PREDICTION = re.compile(r"\bPREDICTION\s*:\s*(UP|DOWN|FLAT)\b", re.IGNORECASE)


class LessonSynthesizer:
    """Produce lessons from an ``AgentRun`` and the cycle's observations."""

    def synthesize(
        self,
        *,
        run: AgentRun,
        cycle: int,
        topic: str,
        observations: list[Observation],
    ) -> list[Lesson]:
        lessons = self._verified_lessons(
            run=run,
            cycle=cycle,
            topic=topic,
            observations=observations,
        )[:MAX_LESSONS_PER_CYCLE]
        sequence = len(lessons)
        for result in run.results:
            for claim in result.claims:
                if len(lessons) >= MAX_LESSONS_PER_CYCLE:
                    break
                lessons.append(
                    Lesson(
                        lesson_id=self._lesson_id(topic, cycle, sequence),
                        cycle=cycle,
                        topic=topic,
                        kind=claim.kind.value,
                        statement=claim.statement,
                        evidence_ids=list(claim.evidence_ids),
                        invalidation_conditions=list(
                            claim.invalidation_conditions
                        ),
                        source_run_id=run.run_id,
                        source_agent_id=result.agent_id,
                        validation_status=LessonValidationStatus.CANDIDATE,
                        tags=[topic, claim.kind.value],
                    )
                )
                sequence += 1
        return lessons

    def _verified_lessons(
        self,
        *,
        run: AgentRun,
        cycle: int,
        topic: str,
        observations: list[Observation],
    ) -> list[Lesson]:
        lessons: list[Lesson] = []
        sequence = 0
        for observation in observations:
            verified = observation.verified_result
            if verified is not None:
                lessons.append(
                    Lesson(
                        lesson_id=self._lesson_id(topic, cycle, sequence),
                        cycle=cycle,
                        topic=topic,
                        kind="outcome",
                        statement=verified.statement,
                        evidence_ids=[observation.identifier],
                        invalidation_conditions=[
                            "仅代表记录区间内的历史回测，不构成未来收益保证。"
                        ],
                        source_run_id=run.run_id,
                        source_agent_id=None,
                        validation_status=LessonValidationStatus.VERIFIED,
                        validation_method=verified.validation_method,
                        tags=[topic, "verified", *verified.tags],
                        metadata=verified.metadata,
                    )
                )
                sequence += 1

            realized = observation.realized_outcome
            if realized is None:
                continue
            for result in run.results:
                prediction = self._prediction(result)
                if prediction is None:
                    continue
                correct = prediction == realized.direction.upper()
                symbol = str(observation.metadata.get("symbol", "unknown"))
                lessons.append(
                    Lesson(
                        lesson_id=self._lesson_id(topic, cycle, sequence),
                        cycle=cycle,
                        topic=topic,
                        kind="outcome",
                        statement=(
                            f"{result.agent_id} 对 {symbol} 的 past-only 预测为 "
                            f"{prediction}，实际为 {realized.direction.upper()}"
                            f"（{realized.total_return:+.2f}%，截至 "
                            f"{realized.horizon_end}），判断"
                            f"{'正确' if correct else '错误'}。"
                        ),
                        evidence_ids=[observation.identifier],
                        invalidation_conditions=[
                            "该评分仅对本标的与切分区间有效，需累计更多独立窗口。"
                        ],
                        source_run_id=run.run_id,
                        source_agent_id=result.agent_id,
                        validation_status=LessonValidationStatus.VERIFIED,
                        validation_method="realized_direction_match_v1",
                        tags=[
                            topic,
                            "verified",
                            "prediction",
                            symbol,
                            "correct" if correct else "incorrect",
                        ],
                        metadata={
                            "symbol": symbol,
                            "prediction": prediction,
                            "realized_direction": realized.direction.upper(),
                            "realized_return": realized.total_return,
                            "horizon_end": realized.horizon_end,
                            "correct": correct,
                        },
                    )
                )
                sequence += 1
        return lessons

    @staticmethod
    def _prediction(result: object) -> str | None:
        summary = str(getattr(result, "summary", "")).strip()
        first_line = summary.splitlines()[0] if summary else ""
        matched = _PREDICTION.fullmatch(first_line.strip())
        return matched.group(1).upper() if matched is not None else None

    @staticmethod
    def _lesson_id(topic: str, cycle: int, sequence: int) -> str:
        prefix = (
            "MKT"
            if topic.startswith("market")
            else "STRAT"
            if topic.startswith("strategy")
            else "BT"
        )
        return f"L-{prefix}-{cycle:06d}-{sequence:03d}"


__all__ = ["LessonSynthesizer", "MAX_LESSONS_PER_CYCLE"]
