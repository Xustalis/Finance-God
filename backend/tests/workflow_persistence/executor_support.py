from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finance_god.agents.catalog import AgentGovernanceCatalog
from finance_god.agents.contracts import WorkflowKey
from finance_god.domain.models import VersionReference
from finance_god.infrastructure.persistence.workflow_persistence import (
    WorkflowEventRow,
    WorkflowExecutionAuditRow,
    WorkflowUnitOfWork,
)
from finance_god.orchestration.task_plans import TaskPlan, TaskPlanFactory
from finance_god.orchestration.workflow_commands import (
    WorkflowCommandService,
    WorkflowCreateCommand,
)
from finance_god.orchestration.workflow_executor import (
    WorkflowExecutionReport,
    WorkflowExecutor,
)
from finance_god.orchestration.workflow_registry import FormalWorkflowRegistry
from tests.workflows.support import AdvancingClock
from tests.workflows.test_executor import (
    GovernedRunner,
    SequencedControls,
)

NOW = datetime(2026, 7, 24, tzinfo=timezone.utc)
MARKET_INPUT = (
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


class FixedRunIds:
    def __init__(self, run_id: str) -> None:
        self._run_id = run_id

    def new(self) -> str:
        return self._run_id


async def exercise_persisted_executor(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    suffix: str,
    workflow_key: WorkflowKey,
    parallel_agent_layer: bool = False,
    invalid_results: dict[str, str] | None = None,
) -> tuple[
    WorkflowExecutionReport,
    GovernedRunner,
    tuple[WorkflowEventRow, ...],
    tuple[WorkflowExecutionAuditRow, ...],
]:
    catalog = AgentGovernanceCatalog()
    registry = FormalWorkflowRegistry.build_default(catalog)
    input_versions = (
        ORDER_INPUT
        if workflow_key
        in {WorkflowKey.ORDER_REVIEW, WorkflowKey.SIMULATION_EXECUTION}
        else MARKET_INPUT
    )
    runner = GovernedRunner(invalid_results=invalid_results)
    async with WorkflowUnitOfWork(session_factory) as uow:
        commands = WorkflowCommandService(
            registry=registry,
            repository=uow.workflows,
            run_ids=FixedRunIds(f"persisted-{suffix}"),
        )
        receipt = await commands.create(
            WorkflowCreateCommand(
                idempotency_key=f"persisted-{suffix}-request",
                workflow_key=workflow_key,
                request_intent="Exercise the real persisted executor.",
                owner_id="user-1",
                scope={"workspace": "desk-1"},
                input_versions=input_versions,
                requested_at=NOW,
            )
        )
        plan = TaskPlanFactory(catalog, registry).formal(
            plan_id=f"persisted-{suffix}-plan",
            owner_id="user-1",
            workflow_key=workflow_key,
            input_versions=input_versions,
            route_reason="persistence executor contract",
        )
        if parallel_agent_layer:
            plan = _parallelize_agent_layer(plan)
            runner.sleeps.update(
                {
                    "governed_agents_a": 0.02,
                    "governed_agents_b": 0.02,
                }
            )
        executor = WorkflowExecutor(
            registry=registry,
            repository=uow.workflows,
            runner=runner,
            controls=SequencedControls(),
            clock=AdvancingClock(),
        )
        report = await executor.execute(run_id=receipt.run.run_id, plan=plan)
        events = await uow.workflows.list_events(receipt.run.run_id)
        audits = await uow.workflows.list_execution_audits(receipt.run.run_id)
        await uow.commit()
    return report, runner, events, audits


def _parallelize_agent_layer(plan: TaskPlan) -> TaskPlan:
    governed_index = next(
        index
        for index, node in enumerate(plan.nodes)
        if node.node_id == "governed_agents"
    )
    governed = plan.nodes[governed_index]
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
    nodes = list(plan.nodes)
    nodes[governed_index : governed_index + 1] = [left, right]
    finalizer_index = next(
        index for index, node in enumerate(nodes) if node.is_finalizer
    )
    nodes[finalizer_index] = nodes[finalizer_index].model_copy(
        update={"dependencies": (left.node_id, right.node_id)}
    )
    return TaskPlan(
        **{
            **plan.model_dump(),
            "nodes": tuple(nodes),
            "maximum_total_attempts": (
                plan.maximum_total_attempts
                + governed.retry_budget.total_attempt_limit
            ),
            "dynamic": True,
        }
    )
