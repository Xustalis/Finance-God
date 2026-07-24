from __future__ import annotations

import unittest

from research_runtime import AgentRoutingError, AssetKind
from research_runtime.models import EvidenceRecord

from finance_god.experiments import build_offline_orchestrator
from finance_god.orchestration.workflows import (
    WorkflowArtifactKind,
    WorkflowBlockReason,
    WorkflowContext,
    WorkflowExecutor,
    WorkflowIntent,
    WorkflowSelector,
    WorkflowStatus,
)
from scripts.run_workflow_experiments import experiment_contexts


def evidence() -> list[EvidenceRecord]:
    return [
        EvidenceRecord(
            identifier="E1",
            source="Test evidence",
            excerpt="Versioned evidence for a workflow test.",
        )
    ]


class WorkflowSelectorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.selector = WorkflowSelector()

    def test_user_pause_has_highest_priority(self) -> None:
        selection = self.selector.select(
            WorkflowContext(
                intent=WorkflowIntent.STRATEGY_VALIDATION,
                subject="Paused strategy",
                evidence=evidence(),
                user_paused=True,
                hard_risk_blocked=True,
                cooldown_active=True,
                market_data_usable=False,
                mandate_active=False,
            )
        )

        self.assertEqual(selection.block_reason, WorkflowBlockReason.USER_PAUSED)
        self.assertIsNone(selection.definition)

    def test_hard_risk_blocks_before_lower_priority_routes(self) -> None:
        selection = self.selector.select(
            WorkflowContext(
                intent=WorkflowIntent.PORTFOLIO_STRESS,
                subject="Blocked portfolio",
                evidence=evidence(),
                hard_risk_blocked=True,
                cooldown_active=True,
                market_data_usable=False,
            )
        )

        self.assertEqual(selection.block_reason, WorkflowBlockReason.HARD_RISK)

    def test_cooldown_selects_review_only_workflow(self) -> None:
        selection = self.selector.select(
            WorkflowContext(
                intent=WorkflowIntent.STRATEGY_VALIDATION,
                subject="Cooldown strategy",
                evidence=evidence(),
                cooldown_active=True,
            )
        )

        self.assertEqual(selection.definition.workflow_key, "review_only")

    def test_stale_data_selects_data_quality_review(self) -> None:
        selection = self.selector.select(
            WorkflowContext(
                intent=WorkflowIntent.MARKET_CONTEXT,
                subject="Stale market",
                evidence=evidence(),
                market_data_usable=False,
            )
        )

        self.assertEqual(selection.definition.workflow_key, "data_quality_review")


class WorkflowExecutionTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.executor = WorkflowExecutor(build_offline_orchestrator())

    async def test_all_experiment_scenarios_produce_expected_artifacts(self) -> None:
        expected = {
            "01_company_research": (
                WorkflowArtifactKind.RESEARCH_MEMO,
                WorkflowStatus.COMPLETED,
            ),
            "02_market_context": (
                WorkflowArtifactKind.MARKET_CONTEXT,
                WorkflowStatus.COMPLETED,
            ),
            "03_portfolio_stress": (
                WorkflowArtifactKind.PORTFOLIO_RISK_REVIEW,
                WorkflowStatus.COMPLETED,
            ),
            "04_strategy_validation": (
                WorkflowArtifactKind.STRATEGY_VALIDATION_DOSSIER,
                WorkflowStatus.COMPLETED,
            ),
            "05_cooldown_review_only": (
                WorkflowArtifactKind.REVIEW_ONLY_MEMO,
                WorkflowStatus.ATTENTION_REQUIRED,
            ),
            "06_stale_data_review": (
                WorkflowArtifactKind.DATA_QUALITY_REPORT,
                WorkflowStatus.ATTENTION_REQUIRED,
            ),
            "07_user_pause_block": (
                WorkflowArtifactKind.WORKFLOW_BLOCK_NOTICE,
                WorkflowStatus.BLOCKED,
            ),
        }

        for name, context in experiment_contexts():
            with self.subTest(name=name):
                run = await self.executor.execute(workflow_id=name, context=context)
                self.assertEqual(
                    (run.artifact.artifact_kind, run.artifact.status),
                    expected[name],
                )
                self.assertIn(run.workflow_id, run.artifact.to_markdown())
                self.assertEqual(
                    run.workflow_id,
                    type(run).model_validate_json(run.model_dump_json()).workflow_id,
                )

    async def test_stage_outputs_are_forwarded_as_evidence(self) -> None:
        name, context = experiment_contexts()[0]

        run = await self.executor.execute(workflow_id=name, context=context)

        second_stage_claim = run.stage_runs[1].run.results[0].claims[0]
        final_stage_claim = run.stage_runs[2].run.results[0].claims[0]
        self.assertEqual(second_stage_claim.evidence_ids, ["WF_S1_A6"])
        self.assertEqual(final_stage_claim.evidence_ids, ["WF_S2_A6"])

    async def test_monitor_workflow_surfaces_missing_resources(self) -> None:
        context = WorkflowContext(
            intent=WorkflowIntent.MARKET_CONTEXT,
            subject="Market without data",
            asset_kind=AssetKind.MARKET,
            evidence=evidence(),
            stage_payloads={
                "market_monitor": {
                    "kind": "market_regime",
                    "subject": "Market without data",
                    "symbol": "510300.SH",
                    "option_underlying": "510300.SH",
                    "start_date": "20260701",
                    "end_date": "20260723",
                }
            },
        )

        with self.assertRaisesRegex(AgentRoutingError, "unavailable resources"):
            await self.executor.execute(
                workflow_id="missing_resources",
                context=context,
            )

    async def test_blocked_workflow_does_not_call_agents(self) -> None:
        context = WorkflowContext(
            intent=WorkflowIntent.PORTFOLIO_STRESS,
            subject="Paused portfolio",
            evidence=evidence(),
            user_paused=True,
        )

        run = await self.executor.execute(workflow_id="paused", context=context)

        self.assertEqual(run.stage_runs, [])
        self.assertEqual(run.artifact.agent_ids, [])
        self.assertEqual(run.artifact.status, WorkflowStatus.BLOCKED)

    async def test_invalid_workflow_id_fails_before_execution(self) -> None:
        context = WorkflowContext(
            intent=WorkflowIntent.COMPANY_RESEARCH,
            subject="Invalid id",
            evidence=evidence(),
        )

        with self.assertRaisesRegex(ValueError, "workflow_id"):
            await self.executor.execute(workflow_id="contains spaces", context=context)


if __name__ == "__main__":
    unittest.main()
