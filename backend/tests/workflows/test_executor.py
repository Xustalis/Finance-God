from __future__ import annotations

import asyncio
import unittest
from collections import defaultdict
from datetime import datetime, timezone

from finance_god.agents.catalog import AgentGovernanceCatalog
from finance_god.agents.contracts import (
    FailureKind,
    NodeRequirement,
    OrderReviewMode,
    WorkflowKey,
)
from finance_god.domain.models import (
    AuditReference,
    RiskCheckResult,
    RiskCheckStatus,
    RiskReason,
    RiskSeverity,
    VersionReference,
    WorkflowRunStatus,
)
from finance_god.orchestration.task_plans import TaskPlan, TaskPlanFactory
from finance_god.orchestration.workflow_commands import (
    WorkflowCommandService,
    WorkflowCreateCommand,
)
from finance_god.orchestration.workflow_executor import (
    NodeExecutionContext,
    NodeExecutionError,
    NodeExecutionOutcome,
    WorkflowControlState,
    WorkflowExecutor,
)
from finance_god.orchestration.workflow_registry import (
    FormalWorkflowRegistry,
    WorkflowNodeDefinition,
)
from finance_god.orchestration.workflow_results import (
    OrderRiskCheckNodeResult,
    SimulationFactNodeResult,
)
from tests.workflows.support import (
    AdvancingClock,
    AsyncMemoryWorkflowRepository,
    SequenceRunIds,
)


INPUT = (
    VersionReference(
        object_type="market_snapshot",
        object_id="XNAS:AAPL",
        version="v1",
    ),
)
ORDER_INPUT = (
    VersionReference(
        object_type="order_draft",
        object_id="order-1",
        version="7",
    ),
)
NOW = datetime(2026, 7, 24, tzinfo=timezone.utc)


class SequencedControls:
    def __init__(self, *states: WorkflowControlState) -> None:
        self.states = list(states) or [WorkflowControlState()]
        self.calls = 0

    def current(self, run_id: str) -> WorkflowControlState:
        del run_id
        index = min(self.calls, len(self.states) - 1)
        self.calls += 1
        return self.states[index]


class GovernedRunner:
    def __init__(
        self,
        *,
        fail: dict[str, list[Exception]] | None = None,
        sleeps: dict[str, float] | None = None,
        quality_passed: bool = True,
        final_type: str | None = None,
        invalid_results: dict[str, str] | None = None,
    ) -> None:
        self.fail = defaultdict(list, fail or {})
        self.sleeps = sleeps or {}
        self.quality_passed = quality_passed
        self.final_type = final_type
        self.invalid_results = invalid_results or {}
        self.calls: list[str] = []
        self.attempts: defaultdict[str, int] = defaultdict(int)
        self.active = 0
        self.maximum_parallel = 0

    async def run(
        self,
        node: WorkflowNodeDefinition,
        context: NodeExecutionContext,
    ) -> NodeExecutionOutcome:
        self.calls.append(node.node_id)
        self.attempts[node.node_id] += 1
        self.active += 1
        self.maximum_parallel = max(self.maximum_parallel, self.active)
        try:
            await asyncio.sleep(self.sleeps.get(node.node_id, 0))
            failures = self.fail[node.node_id]
            if failures:
                raise failures.pop(0)
            deterministic_result = self._deterministic_result(node, context)
            if isinstance(deterministic_result, OrderRiskCheckNodeResult):
                artifact_reference = deterministic_result.risk_check_reference
            elif isinstance(deterministic_result, SimulationFactNodeResult):
                artifact_reference = deterministic_result.result_reference
            else:
                artifact_type = (
                    self.final_type or context.final_artifact_type
                    if node.is_finalizer
                    else "WorkflowNodeArtifact"
                )
                artifact_reference = VersionReference(
                    object_type=artifact_type,
                    object_id=f"{context.run_id}:{node.node_id}:artifact",
                    version=f"attempt-{self.attempts[node.node_id]}",
                )
            if self.invalid_results.get(node.service_id or "") == "wrong_artifact":
                artifact_reference = VersionReference(
                    object_type="WorkflowNodeArtifact",
                    object_id=f"{context.run_id}:{node.node_id}:wrong",
                    version="v1",
                )
            return NodeExecutionOutcome(
                node_id=node.node_id,
                artifact_reference=artifact_reference,
                evidence_references=(
                    VersionReference(
                        object_type="Evidence",
                        object_id=f"{context.run_id}:{node.node_id}:evidence",
                        version="v1",
                    ),
                ),
                contribution_references=(
                    VersionReference(
                        object_type="NodeContribution",
                        object_id=f"{context.run_id}:{node.node_id}:contribution",
                        version="v1",
                    ),
                ),
                permissions_used=tuple(sorted(node.tool_allowlist)),
                pending_actions=(f"review:{node.node_id}",),
                quality_gate_passed=(
                    self.quality_passed if node.is_quality_gate else None
                ),
                deterministic_result=deterministic_result,
            )
        finally:
            self.active -= 1

    def _deterministic_result(
        self,
        node: WorkflowNodeDefinition,
        context: NodeExecutionContext,
    ) -> OrderRiskCheckNodeResult | SimulationFactNodeResult | None:
        order_reference = next(
            (
                reference
                for reference in context.input_versions
                if reference.object_type == "order_draft"
            ),
            None,
        )
        if node.service_id == "risk.pre_submit":
            if order_reference is None:
                raise ValueError("order risk test requires an order input")
            invalid = self.invalid_results.get(node.service_id)
            soft_confirmation = (
                AuditReference(
                    audit_id=f"soft-confirmation:{context.run_id}",
                    actor_id=context.owner_id,
                    recorded_at=NOW,
                )
                if invalid == "soft_confirmed"
                else None
            )
            risk_check = RiskCheckResult(
                risk_check_id=f"risk:{context.run_id}",
                revision=3 if soft_confirmation else 2,
                status=(
                    RiskCheckStatus.CONFIRMATION_REQUIRED
                    if soft_confirmation
                    else RiskCheckStatus.PASSED
                ),
                order_version=order_reference,
                rule_version=VersionReference(
                    object_type="risk_rules",
                    object_id="simulation-risk",
                    version="v1",
                ),
                reasons=(
                    (
                        RiskReason(
                            code="soft_limit",
                            severity=RiskSeverity.SOFT,
                            message="Explicit confirmation required.",
                        ),
                    )
                    if soft_confirmation
                    else ()
                ),
                checked_at=NOW,
                expires_at=NOW.replace(hour=23),
                soft_confirmation=soft_confirmation,
                input_versions=(order_reference,),
                invalidated_by_versions=(),
                audit_reference=AuditReference(
                    audit_id=f"risk-audit:{context.run_id}",
                    actor_id="risk-engine",
                    recorded_at=NOW,
                ),
            )
            result = OrderRiskCheckNodeResult(
                owner_id=context.owner_id,
                order_reference=order_reference,
                risk_check_reference=VersionReference(
                    object_type="RiskCheckResult",
                    object_id=risk_check.risk_check_id,
                    version=str(risk_check.revision),
                ),
                risk_check=risk_check,
            )
            if invalid == "missing":
                return None
            if invalid == "wrong_owner":
                return result.model_copy(update={"owner_id": "other-user"})
            if invalid == "expired":
                expired_check = risk_check.model_copy(
                    update={"expires_at": NOW}
                )
                return result.model_copy(update={"risk_check": expired_check})
            return result
        result_types = {
            "simulation.order_accept": (
                "SimulationOrderAcceptance",
                "SimulationOrder",
            ),
            "simulation.market_validate": (
                "SimulationMarketValidation",
                "MarketValidation",
            ),
            "simulation.match": ("SimulationMatch", "SimulationFill"),
            "simulation.ledger_update": (
                "SimulationLedgerUpdate",
                "LedgerEntry",
            ),
        }
        if node.service_id not in result_types:
            return None
        if order_reference is None:
            raise ValueError("simulation fact test requires an order input")
        result_type, fact_type = result_types[node.service_id]
        result = SimulationFactNodeResult(
            service_id=node.service_id,
            owner_id=context.owner_id,
            order_reference=order_reference,
            accepted=True,
            result_reference=VersionReference(
                object_type=result_type,
                object_id=f"{context.run_id}:{node.node_id}:result",
                version="v1",
            ),
            fact_references=(
                VersionReference(
                    object_type=fact_type,
                    object_id=f"{context.run_id}:{node.node_id}:fact",
                    version="v1",
                ),
            ),
        )
        invalid = self.invalid_results.get(node.service_id)
        if invalid == "missing":
            return None
        if invalid == "rejected":
            return result.model_copy(update={"accepted": False})
        if invalid == "wrong_owner":
            return result.model_copy(update={"owner_id": "other-user"})
        return result


class WorkflowExecutorTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.catalog = AgentGovernanceCatalog()
        self.registry = FormalWorkflowRegistry.build_default(self.catalog)
        self.factory = TaskPlanFactory(self.catalog, self.registry)
        self.repository = AsyncMemoryWorkflowRepository()
        self.commands = WorkflowCommandService(
            registry=self.registry,
            repository=self.repository,
            run_ids=SequenceRunIds(),
        )
        self.clock = AdvancingClock()

    async def make_run(
        self,
        key: WorkflowKey,
        *,
        suffix: str,
    ) -> str:
        receipt = await self.commands.create(
            WorkflowCreateCommand(
                idempotency_key=f"workflow-{suffix}",
                workflow_key=key,
                request_intent=f"Execute {key.value}.",
                owner_id="user-1",
                scope={"workspace": "desk-1"},
                input_versions=self.inputs_for(key),
                requested_at=NOW,
            )
        )
        return receipt.run.run_id

    def plan(
        self,
        key: WorkflowKey,
        *,
        suffix: str,
        **changes: object,
    ) -> TaskPlan:
        plan = self.factory.formal(
            plan_id=f"plan-{suffix}",
            owner_id="user-1",
            workflow_key=key,
            input_versions=self.inputs_for(key),
            route_reason=f"test route {suffix}",
            **changes,
        )
        return plan

    @staticmethod
    def inputs_for(key: WorkflowKey) -> tuple[VersionReference, ...]:
        if key in {WorkflowKey.ORDER_REVIEW, WorkflowKey.SIMULATION_EXECUTION}:
            return ORDER_INPUT
        return INPUT

    def executor(
        self,
        runner: GovernedRunner,
        controls: SequencedControls | None = None,
    ) -> WorkflowExecutor:
        return WorkflowExecutor(
            registry=self.registry,
            repository=self.repository,
            runner=runner,
            controls=controls or SequencedControls(),
            clock=self.clock,
        )

    async def test_full_dag_executes_and_persists_manifest(self) -> None:
        run_id = await self.make_run(WorkflowKey.COMPANY_RESEARCH, suffix="full")
        plan = self.plan(WorkflowKey.COMPANY_RESEARCH, suffix="full")
        runner = GovernedRunner()
        report = await self.executor(runner).execute(run_id=run_id, plan=plan)
        self.assertEqual(report.run.status, WorkflowRunStatus.COMPLETED)
        self.assertTrue(report.run.trade_eligible)
        self.assertEqual(set(runner.calls), {node.node_id for node in plan.nodes})
        self.assertFalse(report.pending_actions_executed)
        completed_payload = next(
            payload
            for _, _, event, payload in reversed(self.repository.events)
            if event == "workflow_completed"
        )
        self.assertEqual(completed_payload["pending_actions_executed"], False)
        self.assertEqual(completed_payload["input_versions"][0]["version"], "v1")
        self.assertTrue(completed_payload["evidence"])
        self.assertTrue(completed_payload["contributions"])

    async def test_same_dag_layer_runs_in_parallel(self) -> None:
        run_id = await self.make_run(WorkflowKey.COMPANY_RESEARCH, suffix="parallel")
        base = self.plan(WorkflowKey.COMPANY_RESEARCH, suffix="parallel")
        governed_index = next(
            index
            for index, node in enumerate(base.nodes)
            if node.node_id == "governed_agents"
        )
        governed = base.nodes[governed_index]
        midpoint = len(governed.agent_ids) // 2
        left = governed.model_copy(
            update={
                "node_id": "governed_agents_a",
                "agent_ids": governed.agent_ids[:midpoint],
            }
        )
        right = governed.model_copy(
            update={
                "node_id": "governed_agents_b",
                "agent_ids": governed.agent_ids[midpoint:],
            }
        )
        nodes = list(base.nodes)
        nodes[governed_index : governed_index + 1] = [left, right]
        finalizer_index = next(
            index for index, node in enumerate(nodes) if node.is_finalizer
        )
        nodes[finalizer_index] = nodes[finalizer_index].model_copy(
            update={"dependencies": (left.node_id, right.node_id)}
        )
        plan = TaskPlan(
            **{
                **base.model_dump(),
                "nodes": tuple(nodes),
                "maximum_total_attempts": (
                    base.maximum_total_attempts
                    + governed.retry_budget.total_attempt_limit
                ),
                "dynamic": True,
            }
        )
        runner = GovernedRunner(
            sleeps={
                left.node_id: 0.03,
                right.node_id: 0.03,
            }
        )
        report = await self.executor(runner).execute(run_id=run_id, plan=plan)
        self.assertEqual(report.run.status, WorkflowRunStatus.COMPLETED)
        self.assertGreaterEqual(runner.maximum_parallel, 2)

    async def test_classified_transient_failure_retries(self) -> None:
        run_id = await self.make_run(WorkflowKey.COMPANY_RESEARCH, suffix="retry")
        plan = self.plan(WorkflowKey.COMPANY_RESEARCH, suffix="retry")
        target = plan.nodes[0].node_id
        runner = GovernedRunner(
            fail={
                target: [
                    NodeExecutionError(FailureKind.TRANSIENT, "temporary")
                ]
            }
        )
        report = await self.executor(runner).execute(run_id=run_id, plan=plan)
        self.assertEqual(report.run.status, WorkflowRunStatus.COMPLETED)
        self.assertEqual(runner.attempts[target], 2)

    async def test_validation_failure_does_not_retry_or_fallback(self) -> None:
        run_id = await self.make_run(
            WorkflowKey.COMPANY_RESEARCH,
            suffix="validation",
        )
        plan = self.plan(WorkflowKey.COMPANY_RESEARCH, suffix="validation")
        target = plan.nodes[0].node_id
        runner = GovernedRunner(
            fail={
                target: [
                    NodeExecutionError(FailureKind.VALIDATION, "invalid output")
                ]
            }
        )
        report = await self.executor(runner).execute(run_id=run_id, plan=plan)
        self.assertEqual(report.run.status, WorkflowRunStatus.FAILED)
        self.assertEqual(runner.attempts[target], 1)
        self.assertEqual(len(report.outcomes), 0)

    async def test_required_node_timeout_is_terminal(self) -> None:
        run_id = await self.make_run(
            WorkflowKey.COMPANY_RESEARCH,
            suffix="node-timeout",
        )
        base = self.plan(WorkflowKey.COMPANY_RESEARCH, suffix="node-timeout")
        target = base.nodes[0]
        nodes = (
            target.model_copy(update={"timeout_seconds": 1}),
            *base.nodes[1:],
        )
        plan = TaskPlan(**{**base.model_dump(), "nodes": nodes})
        runner = GovernedRunner(sleeps={target.node_id: 1.1})
        report = await self.executor(runner).execute(run_id=run_id, plan=plan)
        self.assertEqual(report.run.status, WorkflowRunStatus.TIMED_OUT)
        self.assertTrue(report.failures[0].timed_out)

    async def test_nonblocking_failure_is_audited_without_rollback(self) -> None:
        run_id = await self.make_run(
            WorkflowKey.COMPANY_RESEARCH,
            suffix="nonblocking",
        )
        base = self.plan(WorkflowKey.COMPANY_RESEARCH, suffix="nonblocking")
        target = base.nodes[0]
        nodes = (
            target.model_copy(
                update={"requirement": NodeRequirement.NON_BLOCKING}
            ),
            *base.nodes[1:],
        )
        plan = TaskPlan(**{**base.model_dump(), "nodes": nodes})
        runner = GovernedRunner(
            fail={
                target.node_id: [
                    NodeExecutionError(FailureKind.VALIDATION, "advice unavailable")
                ]
            }
        )
        report = await self.executor(runner).execute(run_id=run_id, plan=plan)
        self.assertEqual(report.run.status, WorkflowRunStatus.COMPLETED)
        self.assertIn("advice unavailable", report.run.errors)
        self.assertIn(
            "non_blocking_node_failed",
            [event for _, event, _, _ in self.repository.audits],
        )

    async def test_pause_and_hard_risk_prestart_make_zero_runner_calls(self) -> None:
        for suffix, state, expected_reason in (
            (
                "pause",
                WorkflowControlState(user_paused=True),
                "user_paused",
            ),
            (
                "hard",
                WorkflowControlState(hard_risk_blocked=True),
                "hard_risk",
            ),
        ):
            with self.subTest(reason=suffix):
                run_id = await self.make_run(
                    WorkflowKey.COMPANY_RESEARCH,
                    suffix=suffix,
                )
                plan = self.plan(WorkflowKey.COMPANY_RESEARCH, suffix=suffix)
                runner = GovernedRunner()
                report = await self.executor(
                    runner,
                    SequencedControls(state),
                ).execute(run_id=run_id, plan=plan)
                self.assertEqual(report.run.status, WorkflowRunStatus.BLOCKED)
                self.assertEqual(report.run.block_reason.value, expected_reason)
                self.assertEqual(runner.calls, [])

    async def test_runtime_pause_uses_cancellation_protocol(self) -> None:
        run_id = await self.make_run(
            WorkflowKey.COMPANY_RESEARCH,
            suffix="runtime-pause",
        )
        plan = self.plan(WorkflowKey.COMPANY_RESEARCH, suffix="runtime-pause")
        controls = SequencedControls(
            WorkflowControlState(),
            WorkflowControlState(),
            WorkflowControlState(user_paused=True),
        )
        runner = GovernedRunner()
        report = await self.executor(runner, controls).execute(
            run_id=run_id,
            plan=plan,
        )
        self.assertEqual(report.run.status, WorkflowRunStatus.CANCELLED)
        events = [event for _, _, event, _ in self.repository.events]
        self.assertIn("workflow_cancel_requested", events)
        self.assertIn("workflow_cancelling", events)
        self.assertIn("workflow_cancelled", events)
        self.assertGreater(len(runner.calls), 0)
        self.assertLess(len(runner.calls), len(plan.nodes))

    async def test_manual_order_pause_runs_deterministic_only_path(self) -> None:
        run_id = await self.make_run(WorkflowKey.ORDER_REVIEW, suffix="manual")
        plan = self.plan(
            WorkflowKey.ORDER_REVIEW,
            suffix="manual",
            order_review_mode=OrderReviewMode.MANUAL,
            suppress_agents=True,
        )
        runner = GovernedRunner()
        report = await self.executor(
            runner,
            SequencedControls(WorkflowControlState(user_paused=True)),
        ).execute(run_id=run_id, plan=plan)
        self.assertEqual(report.run.status, WorkflowRunStatus.COMPLETED)
        self.assertTrue(runner.calls)
        self.assertTrue(
            all(
                not node.agent_ids
                for node in plan.nodes
                if node.node_id in runner.calls
            )
        )

    async def test_quality_failure_requires_attention(self) -> None:
        run_id = await self.make_run(
            WorkflowKey.COMPANY_RESEARCH,
            suffix="quality",
        )
        plan = self.plan(WorkflowKey.COMPANY_RESEARCH, suffix="quality")
        report = await self.executor(
            GovernedRunner(quality_passed=False)
        ).execute(run_id=run_id, plan=plan)
        self.assertEqual(
            report.run.status,
            WorkflowRunStatus.ATTENTION_REQUIRED,
        )
        self.assertFalse(report.run.trade_eligible)

    async def test_review_and_data_quality_are_never_trade_eligible(self) -> None:
        for key in (WorkflowKey.REVIEW_ONLY, WorkflowKey.DATA_QUALITY_REVIEW):
            with self.subTest(workflow=key.value):
                run_id = await self.make_run(key, suffix=key.value)
                plan = self.plan(key, suffix=key.value)
                report = await self.executor(GovernedRunner()).execute(
                    run_id=run_id,
                    plan=plan,
                )
                self.assertEqual(report.run.status, WorkflowRunStatus.COMPLETED)
                self.assertFalse(report.run.trade_eligible)

    async def test_input_change_expires_completed_result(self) -> None:
        run_id = await self.make_run(
            WorkflowKey.COMPANY_RESEARCH,
            suffix="expire",
        )
        plan = self.plan(WorkflowKey.COMPANY_RESEARCH, suffix="expire")
        executor = self.executor(GovernedRunner())
        completed = await executor.execute(run_id=run_id, plan=plan)
        self.assertEqual(completed.run.status, WorkflowRunStatus.COMPLETED)
        expired = await executor.expire_if_inputs_changed(
            run_id=run_id,
            current_input_versions=(
                VersionReference(
                    object_type="market_snapshot",
                    object_id="XNAS:AAPL",
                    version="v2",
                ),
            ),
        )
        self.assertEqual(expired.status, WorkflowRunStatus.EXPIRED)
        self.assertFalse(expired.trade_eligible)

    async def test_order_review_rejects_untyped_or_invalid_risk_results(
        self,
    ) -> None:
        for mode in ("missing", "wrong_owner", "expired", "wrong_artifact"):
            with self.subTest(mode=mode):
                run_id = await self.make_run(
                    WorkflowKey.ORDER_REVIEW,
                    suffix=f"risk-{mode}",
                )
                plan = self.plan(
                    WorkflowKey.ORDER_REVIEW,
                    suffix=f"risk-{mode}",
                )
                report = await self.executor(
                    GovernedRunner(
                        invalid_results={"risk.pre_submit": mode}
                    )
                ).execute(run_id=run_id, plan=plan)
                self.assertEqual(report.run.status, WorkflowRunStatus.FAILED)
                self.assertFalse(report.run.trade_eligible)
                self.assertIn("risk", report.run.errors[0])

    async def test_order_review_accepts_completed_soft_confirmation(self) -> None:
        run_id = await self.make_run(
            WorkflowKey.ORDER_REVIEW,
            suffix="soft-confirmed",
        )
        plan = self.plan(
            WorkflowKey.ORDER_REVIEW,
            suffix="soft-confirmed",
        )
        report = await self.executor(
            GovernedRunner(
                invalid_results={"risk.pre_submit": "soft_confirmed"}
            )
        ).execute(run_id=run_id, plan=plan)
        self.assertEqual(report.run.status, WorkflowRunStatus.COMPLETED)
        self.assertTrue(report.run.trade_eligible)

    async def test_task_plan_owner_must_match_durable_command_owner(self) -> None:
        run_id = await self.make_run(
            WorkflowKey.ORDER_REVIEW,
            suffix="owner-binding",
        )
        plan = self.plan(
            WorkflowKey.ORDER_REVIEW,
            suffix="owner-binding",
        ).model_copy(update={"owner_id": "other-user"})
        runner = GovernedRunner()
        with self.assertRaisesRegex(ValueError, "persisted workflow owner"):
            await self.executor(runner).execute(run_id=run_id, plan=plan)
        self.assertEqual(runner.calls, [])

    async def test_simulation_required_fact_nodes_reject_missing_or_unaccepted(
        self,
    ) -> None:
        cases = (
            ("simulation.order_accept", "rejected"),
            ("simulation.market_validate", "missing"),
            ("simulation.match", "rejected"),
            ("simulation.ledger_update", "wrong_owner"),
        )
        for service_id, mode in cases:
            with self.subTest(service=service_id, mode=mode):
                run_id = await self.make_run(
                    WorkflowKey.SIMULATION_EXECUTION,
                    suffix=f"facts-{service_id.rsplit('.', 1)[-1]}",
                )
                plan = self.plan(
                    WorkflowKey.SIMULATION_EXECUTION,
                    suffix=f"facts-{service_id.rsplit('.', 1)[-1]}",
                )
                report = await self.executor(
                    GovernedRunner(invalid_results={service_id: mode})
                ).execute(run_id=run_id, plan=plan)
                self.assertEqual(report.run.status, WorkflowRunStatus.FAILED)
                self.assertFalse(report.run.trade_eligible)

    async def test_nonblocking_simulation_monitor_failure_preserves_facts(
        self,
    ) -> None:
        run_id = await self.make_run(
            WorkflowKey.SIMULATION_EXECUTION,
            suffix="monitor-nonblocking",
        )
        plan = self.plan(
            WorkflowKey.SIMULATION_EXECUTION,
            suffix="monitor-nonblocking",
        )
        monitor = next(
            node
            for node in plan.nodes
            if node.service_id == "simulation.execution_monitor"
        )
        runner = GovernedRunner(
            fail={
                monitor.node_id: [
                    NodeExecutionError(
                        FailureKind.VALIDATION,
                        "monitor explanation unavailable",
                    )
                ]
            }
        )
        report = await self.executor(runner).execute(
            run_id=run_id,
            plan=plan,
        )
        self.assertEqual(report.run.status, WorkflowRunStatus.COMPLETED)
        self.assertTrue(report.run.trade_eligible)
        self.assertIn("monitor explanation unavailable", report.run.errors)
        self.assertEqual(
            {
                outcome.deterministic_result.service_id
                for outcome in report.outcomes
                if isinstance(
                    outcome.deterministic_result,
                    SimulationFactNodeResult,
                )
            },
            {
                "simulation.order_accept",
                "simulation.market_validate",
                "simulation.match",
                "simulation.ledger_update",
            },
        )


if __name__ == "__main__":
    unittest.main()
