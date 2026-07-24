from __future__ import annotations

from research_runtime.contracts import (
    AgentAssignment,
    AgentPlan,
    AgentResult,
    AgentRun,
    Claim,
    ClaimKind,
)

from finance_god.learning.contracts import (
    LessonValidationStatus,
    Observation,
    RealizedOutcome,
    VerifiedResult,
)
from finance_god.learning.synthesizer import LessonSynthesizer


def _run(summary: str) -> AgentRun:
    return AgentRun(
        run_id="learn-bt-000001",
        plan=AgentPlan(
            run_id="learn-bt-000001",
            assignments=[AgentAssignment(agent_id="market", reason="test")],
        ),
        results=[
            AgentResult(
                agent_id="market",
                summary=summary,
                claims=[
                    Claim(
                        claim_id="claim-1",
                        author_agent_id="market",
                        kind=ClaimKind.INFERENCE,
                        statement="momentum may persist",
                        evidence_ids=["PRED-1"],
                    )
                ],
            )
        ],
    )


def test_only_strictly_scored_prediction_becomes_verified() -> None:
    observation = Observation(
        identifier="PRED-1",
        source="test",
        excerpt="past only",
        topic="backtest_scoring",
        realized_outcome=RealizedOutcome(
            direction="UP",
            total_return=8.0,
            horizon_end="2026-03-01",
        ),
        metadata={"symbol": "510300.SH"},
    )

    lessons = LessonSynthesizer().synthesize(
        run=_run("PREDICTION: DOWN\nrisk remains"),
        cycle=1,
        topic="backtest_scoring",
        observations=[observation],
    )

    assert lessons[0].validation_status is LessonValidationStatus.VERIFIED
    assert lessons[0].metadata["correct"] is False
    assert lessons[1].validation_status is LessonValidationStatus.CANDIDATE


def test_unstructured_agent_claim_remains_candidate() -> None:
    observation = Observation(
        identifier="PRED-1",
        source="test",
        excerpt="past only",
        topic="backtest_scoring",
        realized_outcome=RealizedOutcome(
            direction="UP",
            total_return=8.0,
            horizon_end="2026-03-01",
        ),
    )

    lessons = LessonSynthesizer().synthesize(
        run=_run("The market looks constructive."),
        cycle=1,
        topic="backtest_scoring",
        observations=[observation],
    )

    assert all(
        lesson.validation_status is LessonValidationStatus.CANDIDATE
        for lesson in lessons
    )


def test_prediction_outside_summary_first_line_is_not_verified() -> None:
    observation = Observation(
        identifier="PRED-1",
        source="test",
        excerpt="past only",
        topic="backtest_scoring",
        realized_outcome=RealizedOutcome(
            direction="UP",
            total_return=8.0,
            horizon_end="2026-03-01",
        ),
    )

    lessons = LessonSynthesizer().synthesize(
        run=_run("analysis first\nPREDICTION: UP"),
        cycle=1,
        topic="backtest_scoring",
        observations=[observation],
    )

    assert all(
        lesson.validation_status is LessonValidationStatus.CANDIDATE
        for lesson in lessons
    )


def test_deterministic_strategy_result_is_verified_before_agent_claims() -> None:
    observation = Observation(
        identifier="STRAT-1",
        source="test",
        excerpt="walk forward",
        topic="strategy_backtest",
        verified_result=VerifiedResult(
            statement="held-out return +2%",
            validation_method="walk_forward_sma_v1",
            tags=["strategy"],
        ),
    )

    lessons = LessonSynthesizer().synthesize(
        run=_run("review"),
        cycle=2,
        topic="strategy_backtest",
        observations=[observation],
    )

    assert lessons[0].validation_status is LessonValidationStatus.VERIFIED
    assert lessons[0].validation_method == "walk_forward_sma_v1"
