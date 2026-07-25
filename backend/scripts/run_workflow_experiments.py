#!/usr/bin/env python3
"""Run deterministic workflow-composition experiments and write review artifacts.

Adapted to the governed fifteen-workflow runtime (TaskPlan + WorkflowExecutor).
All results are produced by a deterministic offline node runner; no model
provider or market-data service is contacted.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from finance_god.agents.catalog import AgentGovernanceCatalog
from finance_god.agents.contracts import WorkflowKey
from finance_god.domain.models import VersionReference
from finance_god.orchestration.task_plans import TaskPlanFactory
from finance_god.orchestration.workflow_commands import (
    WorkflowCommandService,
    WorkflowCreateCommand,
)
from finance_god.orchestration.workflow_executor import (
    NodeExecutionContext,
    NodeExecutionOutcome,
    WorkflowControlState,
    WorkflowExecutor,
    WorkflowNodeDefinition,
)
from finance_god.orchestration.workflow_registry import FormalWorkflowRegistry
from finance_god.orchestration.workflow_selection import (
    WorkflowRoutingContext,
    WorkflowSelector,
)

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = WORKSPACE_ROOT / "artifacts" / "workflow-experiments"
EXPERIMENT_TIME = datetime(2026, 7, 24, 8, 0, tzinfo=timezone.utc)

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


# ---------------------------------------------------------------------------
# In-memory test doubles (mirrors tests/workflows/support.py)
# ---------------------------------------------------------------------------

class SequenceRunIds:
    def __init__(self) -> None:
        self.value = 0

    def new(self) -> str:
        self.value += 1
        return f"workflow-run-{self.value}"


class ExperimentClock:
    def __init__(self) -> None:
        self.value = EXPERIMENT_TIME

    def now(self) -> datetime:
        self.value += timedelta(microseconds=1)
        return self.value


class ExperimentControlPort:
    def __init__(self, state: WorkflowControlState | None = None) -> None:
        self._state = state or WorkflowControlState()

    def current(self, run_id: str) -> WorkflowControlState:
        del run_id
        return self._state


class AsyncMemoryRepository:
    """Minimal in-memory WorkflowRunRepository for experiments."""

    def __init__(self) -> None:
        from finance_god.domain.models import WorkflowRun

        self.runs: dict[str, WorkflowRun] = {}
        self.owners: dict[str, str] = {}
        self.keys: dict[str, tuple[str, str]] = {}
        self.events: list[tuple[str, int, str, dict[str, object]]] = []
        self.audits: list[tuple[str, str, dict[str, object], datetime]] = []
        self.outbox: list[tuple[str, str]] = []

    async def create_queued(
        self,
        *,
        run,
        idempotency_key,
        request_hash,
        request_intent,
        owner_id,
        scope,
        requested_at,
        audit_payload,
        outbox_payload,
    ):
        del request_intent, requested_at
        stable_key = f"{owner_id}|{idempotency_key}"
        existing = self.keys.get(stable_key)
        if existing is not None:
            existing_hash, run_id = existing
            if existing_hash != request_hash:
                raise ValueError("idempotency key was already used with a different request")
            return self.runs[run_id], False
        self.keys[stable_key] = (request_hash, run.run_id)
        self.runs[run.run_id] = run
        self.owners[run.run_id] = owner_id
        self.events.append(
            (run.run_id, run.revision, "workflow_queued", audit_payload)
        )
        self.outbox.append((run.run_id, str(outbox_payload["status"])))
        return run, True

    async def get(self, run_id: str):
        return self.runs.get(run_id)

    async def get_owner_id(self, run_id: str):
        return self.owners.get(run_id)

    async def compare_and_append(
        self, *, run, expected_revision, event_type, event_payload, outbox_topic
    ):
        current = self.runs[run.run_id]
        if current.revision != expected_revision:
            raise RuntimeError("workflow run revision changed")
        if run.revision != expected_revision + 1:
            raise ValueError("CAS append requires exactly one revision")
        self.runs[run.run_id] = run
        self.events.append((run.run_id, run.revision, event_type, event_payload))
        self.outbox.append((run.run_id, outbox_topic))
        return run

    async def append_audit(
        self, *, audit_id, run_id, event_type, payload_json,
        occurred_at, actor_id=None, correlation_id=None
    ):
        del audit_id, actor_id, correlation_id
        if run_id not in self.runs:
            raise LookupError(run_id)
        self.audits.append((run_id, event_type, payload_json, occurred_at))


class ExperimentNodeRunner:
    """Deterministic node runner that returns valid outcomes for every node."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.attempts: defaultdict[str, int] = defaultdict(int)

    async def run(
        self,
        node: WorkflowNodeDefinition,
        context: NodeExecutionContext,
    ) -> NodeExecutionOutcome:
        self.calls.append(node.node_id)
        self.attempts[node.node_id] += 1
        artifact_type = (
            context.final_artifact_type if node.is_finalizer else "WorkflowNodeArtifact"
        )
        return NodeExecutionOutcome(
            node_id=node.node_id,
            artifact_reference=VersionReference(
                object_type=artifact_type,
                object_id=f"{context.run_id}:{node.node_id}:artifact",
                version=f"attempt-{self.attempts[node.node_id]}",
            ),
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
            quality_gate_passed=True if node.is_quality_gate else None,
        )


# ---------------------------------------------------------------------------
# Experiment scenarios
# ---------------------------------------------------------------------------

def experiment_scenarios() -> list[tuple[str, WorkflowRoutingContext, WorkflowControlState]]:
    """Return (name, routing_context, control_state) triples."""
    return [
        (
            "01_company_research",
            WorkflowRoutingContext(
                requested_workflow=WorkflowKey.COMPANY_RESEARCH,
                request_intent="离线实验：对示例基础设施公司进行版本化研究。",
                owner_id="experiment-user",
                scope={"account_id": "sim-1"},
                input_versions=INPUT,
            ),
            WorkflowControlState(),
        ),
        (
            "02_market_context",
            WorkflowRoutingContext(
                requested_workflow=WorkflowKey.MARKET_CONTEXT,
                request_intent="离线实验：评估 A 股市场环境。",
                owner_id="experiment-user",
                scope={"account_id": "sim-1"},
                input_versions=INPUT,
            ),
            WorkflowControlState(),
        ),
        (
            "03_portfolio_stress",
            WorkflowRoutingContext(
                requested_workflow=WorkflowKey.PORTFOLIO_STRESS,
                request_intent="离线实验：对股指与宽基 ETF 组合进行压力测试。",
                owner_id="experiment-user",
                scope={"account_id": "sim-1"},
                input_versions=INPUT,
            ),
            WorkflowControlState(),
        ),
        (
            "04_strategy_validation",
            WorkflowRoutingContext(
                requested_workflow=WorkflowKey.STRATEGY_VALIDATION,
                request_intent="离线实验：验证月度 ETF 动量策略。",
                owner_id="experiment-user",
                scope={"account_id": "sim-1"},
                input_versions=INPUT,
            ),
            WorkflowControlState(),
        ),
        (
            "05_cooldown_review_only",
            WorkflowRoutingContext(
                requested_workflow=WorkflowKey.STRATEGY_VALIDATION,
                request_intent="离线实验：冷静期下仅允许只读复核。",
                owner_id="experiment-user",
                scope={"account_id": "sim-1"},
                input_versions=INPUT,
                cooldown_active=True,
            ),
            WorkflowControlState(),
        ),
        (
            "06_stale_data_review",
            WorkflowRoutingContext(
                requested_workflow=WorkflowKey.MARKET_CONTEXT,
                request_intent="离线实验：陈旧市场数据诊断。",
                owner_id="experiment-user",
                scope={"account_id": "sim-1"},
                input_versions=INPUT,
                data_usable=False,
            ),
            WorkflowControlState(),
        ),
        (
            "07_user_pause_block",
            WorkflowRoutingContext(
                requested_workflow=WorkflowKey.PORTFOLIO_STRESS,
                request_intent="离线实验：用户暂停后的组合请求。",
                owner_id="experiment-user",
                scope={"account_id": "sim-1"},
                input_versions=INPUT,
                user_paused=True,
            ),
            WorkflowControlState(user_paused=True),
        ),
    ]


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _report_to_markdown(name: str, report: object, run: object) -> str:
    """Produce a human-readable Markdown summary of an experiment report."""
    lines = [
        f"# 实验：{name}",
        "",
        "> 所有结果均由离线确定性适配器生成，用于验证编排、门禁和产物结构；"
        "不代表真实投资结论。",
        "",
        f"- **工作流**: {run.workflow_key}",
        f"- **状态**: {run.status.value}",
        f"- **可交易**: {'是' if run.trade_eligible else '否'}",
        f"- **最终产物**: {run.final_artifact or '-'}",
        f"- **错误**: {', '.join(run.errors) if run.errors else '无'}",
    ]
    if run.block_reason is not None:
        lines.append(f"- **阻断原因**: {run.block_reason.value}")
    lines.extend([
        "",
        "## 执行报告",
        "",
        f"- **路由**: {' → '.join(report.routing)}",
        f"- **成功节点**: {len(report.outcomes)}",
        f"- **失败节点**: {len(report.failures)}",
        f"- **待审核动作**: {', '.join(report.pending_actions) if report.pending_actions else '无'}",
        "",
    ])
    if report.outcomes:
        lines.extend(["### 节点产物", ""])
        for outcome in report.outcomes:
            lines.append(
                f"- `{outcome.node_id}` → {outcome.artifact_reference.object_type}"
                f" ({outcome.artifact_reference.object_id})"
            )
        lines.append("")
    if report.failures:
        lines.extend(["### 节点失败", ""])
        for failure in report.failures:
            lines.append(
                f"- `{failure.node_id}` [{failure.requirement.value}]: "
                f"{failure.failure_kind.value if failure.failure_kind else '-'} — "
                f"{failure.error} (attempts={failure.attempts})"
            )
        lines.append("")
    return "\n".join(lines)


def _write_index(output_dir: Path, results: list[tuple[str, object, object]]) -> None:
    lines = [
        "# Multi-Agent 工作流组合实验",
        "",
        "> 所有结果均由离线确定性适配器生成，用于验证编排、门禁和产物结构；"
        "不代表真实投资结论。",
        "",
        "| 实验 | 工作流 | 状态 | 可交易 | 成功节点 | 失败节点 | 路由 |",
        "| --- | --- | --- | --- | ---: | ---: | --- |",
    ]
    for name, report, run in results:
        lines.append(
            f"| [{name}]({name}.md) | {run.workflow_key} | "
            f"{run.status.value} | {'是' if run.trade_eligible else '否'} | "
            f"{len(report.outcomes)} | {len(report.failures)} | "
            f"{' → '.join(report.routing)} |"
        )
    lines.extend([
        "",
        "每个实验同时提供 Markdown 人读报告和 JSON 机器契约。",
        "",
        "## 实验观察",
        "",
        "- 正常研究路径会运行完整 DAG，所有节点产出产物和证据。",
        "- 冷静期通过路由选择切换到只读复核工作流。",
        "- 数据不可用时路由到数据质量诊断工作流。",
        "- 用户暂停时阻断执行，不运行任何节点。",
        "",
    ])
    (output_dir / "index.md").write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main experiment runner
# ---------------------------------------------------------------------------

async def run_experiments(output_dir: Path = DEFAULT_OUTPUT_DIR) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    catalog = AgentGovernanceCatalog()
    registry = FormalWorkflowRegistry.build_default(catalog)
    selector = WorkflowSelector()
    factory = TaskPlanFactory(catalog, registry)
    repository = AsyncMemoryRepository()
    commands = WorkflowCommandService(
        registry=registry,
        repository=repository,
        run_ids=SequenceRunIds(),
    )

    results: list[tuple[str, object, object]] = []

    for name, routing_ctx, control_state in experiment_scenarios():
        # 1. Select workflow via routing rules
        selection = selector.select(routing_ctx, notice_id=f"exp-{name}")
        selected_key = (
            selection.selected_workflow
            if selection.selected_workflow
            else routing_ctx.requested_workflow
        )

        # 2. Determine input versions
        input_versions = (
            ORDER_INPUT
            if selected_key in {WorkflowKey.ORDER_REVIEW, WorkflowKey.SIMULATION_EXECUTION}
            else INPUT
        )

        # 3. Create a durable workflow run
        receipt = await commands.create(
            WorkflowCreateCommand(
                idempotency_key=f"experiment-{name}",
                workflow_key=selected_key,
                request_intent=routing_ctx.request_intent,
                owner_id=routing_ctx.owner_id,
                scope=routing_ctx.scope,
                input_versions=input_versions,
                requested_at=EXPERIMENT_TIME,
            )
        )
        run_id = receipt.run.run_id

        # 4. Build a TaskPlan
        suppress = selection.suppress_agent_nodes if selection.selected_workflow else False
        plan = factory.formal(
            plan_id=f"experiment-plan-{name}",
            owner_id=routing_ctx.owner_id,
            workflow_key=selected_key,
            input_versions=input_versions,
            route_reason=selection.rationale,
            suppress_agents=suppress,
        )

        # 5. Execute via WorkflowExecutor
        runner = ExperimentNodeRunner()
        clock = ExperimentClock()
        executor = WorkflowExecutor(
            registry=registry,
            repository=repository,
            runner=runner,
            controls=ExperimentControlPort(control_state),
            clock=clock,
        )
        report = await executor.execute(run_id=run_id, plan=plan)

        # 6. Write outputs
        final_run = report.run
        (output_dir / f"{name}.json").write_text(
            final_run.model_dump_json(indent=2),
            encoding="utf-8",
        )
        (output_dir / f"{name}.md").write_text(
            _report_to_markdown(name, report, final_run),
            encoding="utf-8",
        )
        results.append((name, report, final_run))
        print(f"  ✓ {name}: {final_run.status.value} ({len(runner.calls)} nodes)")

    _write_index(output_dir, results)
    print(f"\nGenerated {len(results)} workflow experiments in {output_dir}")


if __name__ == "__main__":
    asyncio.run(run_experiments())
