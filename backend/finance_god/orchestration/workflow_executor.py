"""Persistent governed DAG execution for workflow TaskPlans."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from time import monotonic
from typing import Protocol

from pydantic import Field, model_validator

from finance_god.agents.contracts import FailureKind, NodeRequirement, WorkflowKey
from finance_god.domain.models import (
    AuditReference,
    VersionReference,
    WorkflowBlockReason,
    WorkflowCancellationReason,
    WorkflowRun,
    WorkflowRunStatus,
)

from .task_plans import TaskPlan
from .workflow_commands import WorkflowRunRepository
from .workflow_registry import (
    DeterministicResultContract,
    FormalWorkflowRegistry,
    FrozenModel,
    WorkflowNodeDefinition,
)
from .workflow_results import (
    DeterministicNodeResult,
    OrderRiskCheckNodeResult,
    SimulationFactNodeResult,
)


class Clock(Protocol):
    def now(self) -> datetime: ...


class WorkflowControlState(FrozenModel):
    user_paused: bool = False
    hard_risk_blocked: bool = False


class WorkflowControlPort(Protocol):
    def current(self, run_id: str) -> WorkflowControlState: ...


class NodeExecutionError(RuntimeError):
    def __init__(self, kind: FailureKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind


class NodeExecutionOutcome(FrozenModel):
    node_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    artifact_reference: VersionReference
    evidence_references: tuple[VersionReference, ...] = ()
    contribution_references: tuple[VersionReference, ...] = ()
    permissions_used: tuple[str, ...] = ()
    pending_actions: tuple[str, ...] = ()
    quality_gate_passed: bool | None = None
    deterministic_result: DeterministicNodeResult | None = None


class NodeExecutionContext(FrozenModel):
    run_id: str
    owner_id: str
    workflow_key: WorkflowKey
    workflow_version: str
    final_artifact_type: str
    plan_reference: VersionReference
    input_versions: tuple[VersionReference, ...]
    completed_artifacts: tuple[VersionReference, ...]


class WorkflowNodeRunner(Protocol):
    async def run(
        self,
        node: WorkflowNodeDefinition,
        context: NodeExecutionContext,
    ) -> NodeExecutionOutcome: ...


class NodeFailureRecord(FrozenModel):
    node_id: str
    requirement: NodeRequirement
    attempts: int = Field(ge=1)
    failure_kind: FailureKind | None
    timed_out: bool
    error: str = Field(min_length=1, max_length=1_000)


class WorkflowExecutionReport(FrozenModel):
    run: WorkflowRun
    outcomes: tuple[NodeExecutionOutcome, ...]
    failures: tuple[NodeFailureRecord, ...]
    routing: tuple[str, ...]
    pending_actions: tuple[str, ...]
    pending_actions_executed: bool = False

    @model_validator(mode="after")
    def validate_unexecuted_actions(self) -> WorkflowExecutionReport:
        if self.pending_actions_executed:
            raise ValueError("workflow pending actions must remain unexecuted")
        return self


class _NodeAuditRecord(FrozenModel):
    event_type: str
    payload: dict[str, object]
    occurred_at: datetime


class _NodeResult(FrozenModel):
    outcome: NodeExecutionOutcome | None
    failure: NodeFailureRecord | None
    attempts: int
    audits: tuple[_NodeAuditRecord, ...]


class WorkflowExecutor:
    def __init__(
        self,
        *,
        registry: FormalWorkflowRegistry,
        repository: WorkflowRunRepository,
        runner: WorkflowNodeRunner,
        controls: WorkflowControlPort,
        clock: Clock,
    ) -> None:
        self._registry = registry
        self._repository = repository
        self._runner = runner
        self._controls = controls
        self._clock = clock
        self._execution_audit_sequence = 0

    async def execute(
        self,
        *,
        run_id: str,
        plan: TaskPlan,
    ) -> WorkflowExecutionReport:
        run = await self._require_run(run_id)
        owner_id = await self._repository.get_owner_id(run_id)
        if owner_id is None:
            raise LookupError(f"workflow owner does not exist: {run_id}")
        self._validate_plan_binding(run, plan, owner_id=owner_id)
        run = await self._pre_start_control(
            run,
            agent_pause_exempt=plan.agent_pause_exempt,
        )
        if run.status is WorkflowRunStatus.BLOCKED:
            return WorkflowExecutionReport(
                run=run,
                outcomes=(),
                failures=(),
                routing=("pre_start_block",),
                pending_actions=(),
            )
        if run.status is WorkflowRunStatus.QUEUED:
            run = await self._transition(
                run,
                WorkflowRunStatus.RUNNING,
                event_type="workflow_started",
            )
        if run.status is not WorkflowRunStatus.RUNNING:
            raise ValueError(f"workflow run is not executable: {run.status.value}")

        outcomes: list[NodeExecutionOutcome] = []
        failures: list[NodeFailureRecord] = []
        routing = [plan.route_reason]
        pending_actions: set[str] = set()
        try:
            run = await asyncio.wait_for(
                self._execute_dag(
                    run=run,
                    plan=plan,
                    outcomes=outcomes,
                    failures=failures,
                    pending_actions=pending_actions,
                ),
                timeout=plan.maximum_duration_seconds,
            )
        except TimeoutError:
            current = await self._require_run(run_id)
            if current.status is WorkflowRunStatus.RUNNING:
                run = await self._transition(
                    current,
                    WorkflowRunStatus.TIMED_OUT,
                    event_type="workflow_timed_out",
                    errors=(*current.errors, "workflow_duration_limit_exhausted"),
                )
            else:
                run = current
        return WorkflowExecutionReport(
            run=run,
            outcomes=tuple(outcomes),
            failures=tuple(failures),
            routing=tuple(routing),
            pending_actions=tuple(sorted(pending_actions)),
        )

    async def _execute_dag(
        self,
        *,
        run: WorkflowRun,
        plan: TaskPlan,
        outcomes: list[NodeExecutionOutcome],
        failures: list[NodeFailureRecord],
        pending_actions: set[str],
    ) -> WorkflowRun:
        definition = self._registry.get(plan.workflow_key)
        pending = {node.node_id: node for node in plan.nodes}
        terminal: set[str] = set()
        total_attempts = 0
        passed_quality_gates = 0
        while pending:
            run = await self._apply_runtime_control(
                run,
                agent_pause_exempt=plan.agent_pause_exempt,
            )
            if run.status is not WorkflowRunStatus.RUNNING:
                return run
            ready = tuple(
                node
                for node in pending.values()
                if set(node.dependencies).issubset(terminal)
            )
            if not ready:
                raise RuntimeError("TaskPlan execution reached an impossible DAG state")
            remaining_attempts = plan.maximum_total_attempts - total_attempts
            if remaining_attempts < len(ready):
                return await self._transition(
                    run,
                    WorkflowRunStatus.FAILED,
                    event_type="workflow_attempt_limit_exhausted",
                    errors=(*run.errors, "workflow_attempt_limit_exhausted"),
                )
            context = NodeExecutionContext(
                run_id=run.run_id,
                owner_id=plan.owner_id,
                workflow_key=plan.workflow_key,
                workflow_version=plan.workflow_version,
                final_artifact_type=plan.final_artifact_type,
                plan_reference=plan.reference,
                input_versions=plan.input_versions,
                completed_artifacts=tuple(
                    outcome.artifact_reference for outcome in outcomes
                ),
            )
            base_allocation, extra = divmod(remaining_attempts, len(ready))
            allocations = tuple(
                base_allocation + (1 if index < extra else 0)
                for index in range(len(ready))
            )
            results = await asyncio.gather(
                *(
                    self._execute_node(
                        run_id=run.run_id,
                        node=node,
                        context=context,
                        maximum_attempts=allocation,
                    )
                    for node, allocation in zip(ready, allocations, strict=True)
                )
            )
            for result in results:
                for audit in result.audits:
                    await self._append_execution_audit(run.run_id, audit)
            for node, result in zip(ready, results, strict=True):
                total_attempts += result.attempts
                pending.pop(node.node_id)
                terminal.add(node.node_id)
                if result.failure is not None:
                    failures.append(result.failure)
                    if node.requirement is NodeRequirement.REQUIRED:
                        status = (
                            WorkflowRunStatus.TIMED_OUT
                            if result.failure.timed_out
                            else WorkflowRunStatus.FAILED
                        )
                        return await self._transition(
                            run,
                            status,
                            event_type=f"required_node_{status.value}",
                            errors=(*run.errors, result.failure.error),
                        )
                    run = await self._audit_nonblocking_failure(
                        run,
                        result.failure,
                    )
                    continue
                outcome = result.outcome
                if outcome is None:
                    raise RuntimeError("node result lacks outcome and failure")
                outcomes.append(outcome)
                pending_actions.update(outcome.pending_actions)
                run = await self._record_outcome(run, node, outcome)
                if node.is_quality_gate:
                    if not self._quality_gate_passed(node, outcome):
                        return await self._transition(
                            run,
                            WorkflowRunStatus.ATTENTION_REQUIRED,
                            event_type="workflow_quality_attention",
                            errors=(*run.errors, "deterministic_quality_gate_failed"),
                        )
                    passed_quality_gates += 1

        finalizer = next(node for node in plan.nodes if node.is_finalizer)
        final_outcome = next(
            outcome for outcome in outcomes if outcome.node_id == finalizer.node_id
        )
        if final_outcome.artifact_reference.object_type != plan.final_artifact_type:
            return await self._transition(
                run,
                WorkflowRunStatus.FAILED,
                event_type="final_artifact_contract_failed",
                errors=(*run.errors, "final_artifact_type_mismatch"),
            )
        trade_eligible = (
            definition.allows_trade_eligibility
            and passed_quality_gates
            == len([node for node in plan.nodes if node.is_quality_gate])
        )
        return await self._transition(
            run,
            WorkflowRunStatus.COMPLETED,
            event_type="workflow_completed",
            trade_eligible=trade_eligible,
            final_artifact=final_outcome.artifact_reference,
            errors=tuple(failure.error for failure in failures),
            payload={
                "route_reason": plan.route_reason,
                "input_versions": [
                    item.model_dump(mode="json") for item in plan.input_versions
                ],
                "evidence": [
                    item.model_dump(mode="json")
                    for outcome in outcomes
                    for item in outcome.evidence_references
                ],
                "contributions": [
                    item.model_dump(mode="json")
                    for outcome in outcomes
                    for item in outcome.contribution_references
                ],
                "permissions": sorted(
                    {
                        permission
                        for outcome in outcomes
                        for permission in outcome.permissions_used
                    }
                ),
                "pending_actions": sorted(pending_actions),
                "pending_actions_executed": False,
                "non_blocking_errors": [
                    failure.model_dump(mode="json") for failure in failures
                ],
                "deterministic_results": [
                    outcome.deterministic_result.model_dump(mode="json")
                    for outcome in outcomes
                    if outcome.deterministic_result is not None
                ],
            },
        )

    async def _execute_node(
        self,
        *,
        run_id: str,
        node: WorkflowNodeDefinition,
        context: NodeExecutionContext,
        maximum_attempts: int,
    ) -> _NodeResult:
        started = monotonic()
        attempts = 0
        retry_counts = {kind: 0 for kind in FailureKind}
        audits: list[_NodeAuditRecord] = []
        attempt_limit = min(
            maximum_attempts,
            node.retry_budget.total_attempt_limit,
        )
        while attempts < attempt_limit:
            attempts += 1
            elapsed = monotonic() - started
            remaining = node.retry_budget.total_duration_seconds - elapsed
            if remaining <= 0:
                return self._timed_out(
                    node,
                    attempts,
                    "node retry duration exhausted",
                    audits,
                )
            timeout = min(node.timeout_seconds, remaining)
            audits.append(
                self._node_audit(
                event_type="node_attempt_started",
                payload={
                    "node_id": node.node_id,
                    "attempt": attempts,
                    "agent_ids": list(node.agent_ids),
                    "service_id": node.service_id,
                    "tools": sorted(node.tool_allowlist),
                    "data_permissions": sorted(node.data_permissions),
                    "external_actions": sorted(node.external_action_allowlist),
                },
                )
            )
            try:
                outcome = await asyncio.wait_for(
                    self._runner.run(node, context),
                    timeout=timeout,
                )
                self._validate_deterministic_outcome(node, outcome, context)
            except TimeoutError:
                audits.append(
                    self._node_audit(
                    event_type="node_attempt_timed_out",
                    payload={
                        "node_id": node.node_id,
                        "attempt": attempts,
                    },
                    )
                )
                return self._timed_out(
                    node,
                    attempts,
                    "node timeout exhausted",
                    audits,
                )
            except NodeExecutionError as error:
                retry_counts[error.kind] += 1
                audits.append(
                    self._node_audit(
                    event_type="node_attempt_failed",
                    payload={
                        "node_id": node.node_id,
                        "attempt": attempts,
                        "failure_kind": error.kind.value,
                        "error": str(error),
                    },
                    )
                )
                if (
                    retry_counts[error.kind]
                    <= node.retry_budget.retry_limits[error.kind]
                    and attempts < attempt_limit
                ):
                    continue
                return _NodeResult(
                    outcome=None,
                    failure=NodeFailureRecord(
                        node_id=node.node_id,
                        requirement=node.requirement,
                        attempts=attempts,
                        failure_kind=error.kind,
                        timed_out=False,
                        error=str(error),
                    ),
                    attempts=attempts,
                    audits=tuple(audits),
                )
            except Exception as error:
                message = f"unclassified_node_error:{type(error).__name__}:{error}"
                audits.append(
                    self._node_audit(
                    event_type="node_attempt_failed",
                    payload={
                        "node_id": node.node_id,
                        "attempt": attempts,
                        "failure_kind": FailureKind.VALIDATION.value,
                        "error": message,
                    },
                    )
                )
                return _NodeResult(
                    outcome=None,
                    failure=NodeFailureRecord(
                        node_id=node.node_id,
                        requirement=node.requirement,
                        attempts=attempts,
                        failure_kind=FailureKind.VALIDATION,
                        timed_out=False,
                        error=message,
                    ),
                    attempts=attempts,
                    audits=tuple(audits),
                )
            if outcome.node_id != node.node_id:
                audits.append(
                    self._node_audit(
                        event_type="node_attempt_failed",
                        payload={
                            "node_id": node.node_id,
                            "attempt": attempts,
                            "failure_kind": FailureKind.VALIDATION.value,
                            "error": "node outcome identity mismatch",
                        },
                    )
                )
                return _NodeResult(
                    outcome=None,
                    failure=NodeFailureRecord(
                        node_id=node.node_id,
                        requirement=node.requirement,
                        attempts=attempts,
                        failure_kind=FailureKind.VALIDATION,
                        timed_out=False,
                        error="node outcome identity mismatch",
                    ),
                    attempts=attempts,
                    audits=tuple(audits),
                )
            audits.append(
                self._node_audit(
                event_type="node_attempt_completed",
                payload={
                    "node_id": node.node_id,
                    "attempt": attempts,
                    "artifact": outcome.artifact_reference.model_dump(mode="json"),
                    "pending_actions": list(outcome.pending_actions),
                    "pending_actions_executed": False,
                },
                )
            )
            return _NodeResult(
                outcome=outcome,
                failure=None,
                attempts=attempts,
                audits=tuple(audits),
            )
        return self._timed_out(
            node,
            attempts,
            "node attempt limit exhausted",
            audits,
        )

    @staticmethod
    def _timed_out(
        node: WorkflowNodeDefinition,
        attempts: int,
        error: str,
        audits: list[_NodeAuditRecord],
    ) -> _NodeResult:
        return _NodeResult(
            outcome=None,
            failure=NodeFailureRecord(
                node_id=node.node_id,
                requirement=node.requirement,
                attempts=max(1, attempts),
                failure_kind=None,
                timed_out=True,
                error=error,
            ),
            attempts=max(1, attempts),
            audits=tuple(audits),
        )

    def _node_audit(
        self,
        *,
        event_type: str,
        payload: dict[str, object],
    ) -> _NodeAuditRecord:
        return _NodeAuditRecord(
            event_type=event_type,
            payload=payload,
            occurred_at=self._clock.now(),
        )

    async def _append_execution_audit(
        self,
        run_id: str,
        audit: _NodeAuditRecord,
    ) -> None:
        await self._repository.append_audit(
            audit_id=self._next_execution_audit_id(run_id),
            run_id=run_id,
            event_type=audit.event_type,
            payload_json=audit.payload,
            occurred_at=audit.occurred_at,
            actor_id="workflow-executor",
            correlation_id=run_id,
        )

    def _validate_deterministic_outcome(
        self,
        node: WorkflowNodeDefinition,
        outcome: NodeExecutionOutcome,
        context: NodeExecutionContext,
    ) -> None:
        result = outcome.deterministic_result
        if node.agent_ids:
            if result is not None:
                raise NodeExecutionError(
                    FailureKind.VALIDATION,
                    "Agent node cannot return deterministic trade facts",
                )
            return
        if node.result_contract is DeterministicResultContract.ORDER_RISK_CHECK:
            if not isinstance(result, OrderRiskCheckNodeResult):
                raise NodeExecutionError(
                    FailureKind.VALIDATION,
                    "risk.pre_submit requires a typed RiskCheckResult",
                )
            if (
                result.owner_id != context.owner_id
                or result.order_reference not in context.input_versions
                or outcome.artifact_reference != result.risk_check_reference
                or not result.risk_check.can_submit_at(self._clock.now())
            ):
                raise NodeExecutionError(
                    FailureKind.VALIDATION,
                    "risk check is unbound, expired, blocked, or unconfirmed",
                )
            return
        simulation_contracts = {
            DeterministicResultContract.SIMULATION_ORDER_ACCEPTANCE,
            DeterministicResultContract.SIMULATION_MARKET_VALIDATION,
            DeterministicResultContract.SIMULATION_MATCH,
            DeterministicResultContract.SIMULATION_LEDGER_UPDATE,
        }
        if node.result_contract in simulation_contracts:
            if (
                not isinstance(result, SimulationFactNodeResult)
                or result.service_id != node.service_id
                or result.owner_id != context.owner_id
                or result.order_reference not in context.input_versions
                or outcome.artifact_reference != result.result_reference
                or not result.accepted
            ):
                raise NodeExecutionError(
                    FailureKind.VALIDATION,
                    f"{node.service_id} requires accepted typed simulation facts",
                )
            return
        if result is not None:
            raise NodeExecutionError(
                FailureKind.VALIDATION,
                f"{node.service_id} returned an unexpected deterministic result",
            )

    @staticmethod
    def _quality_gate_passed(
        node: WorkflowNodeDefinition,
        outcome: NodeExecutionOutcome,
    ) -> bool:
        if node.result_contract is DeterministicResultContract.ORDER_RISK_CHECK:
            return isinstance(
                outcome.deterministic_result,
                OrderRiskCheckNodeResult,
            )
        return outcome.quality_gate_passed is True

    async def _record_outcome(
        self,
        run: WorkflowRun,
        node: WorkflowNodeDefinition,
        outcome: NodeExecutionOutcome,
    ) -> WorkflowRun:
        current = run.record_completed_node_artifact(
            outcome.artifact_reference,
            audit_reference=self._audit(run, f"node:{node.node_id}:artifact"),
        )
        current = await self._save(
            current,
            expected_revision=run.revision,
            event_type="node_artifact_recorded",
            payload={"node_id": node.node_id},
        )
        for reference in outcome.evidence_references:
            updated = current.record_evidence(
                reference,
                audit_reference=self._audit(
                    current,
                    f"node:{node.node_id}:evidence:{reference.object_id}",
                ),
            )
            current = await self._save(
                updated,
                expected_revision=current.revision,
                event_type="node_evidence_recorded",
                payload={"node_id": node.node_id},
            )
        for reference in outcome.contribution_references:
            updated = current.record_node_contribution(
                reference,
                audit_reference=self._audit(
                    current,
                    f"node:{node.node_id}:contribution:{reference.object_id}",
                ),
            )
            current = await self._save(
                updated,
                expected_revision=current.revision,
                event_type="node_contribution_recorded",
                payload={"node_id": node.node_id},
            )
        return current

    async def _audit_nonblocking_failure(
        self,
        run: WorkflowRun,
        failure: NodeFailureRecord,
    ) -> WorkflowRun:
        await self._repository.append_audit(
            audit_id=self._next_execution_audit_id(run.run_id),
            run_id=run.run_id,
            event_type="non_blocking_node_failed",
            payload_json=failure.model_dump(mode="json"),
            occurred_at=self._clock.now(),
            actor_id="workflow-executor",
            correlation_id=run.run_id,
        )
        return run

    async def _pre_start_control(
        self,
        run: WorkflowRun,
        *,
        agent_pause_exempt: bool,
    ) -> WorkflowRun:
        control = self._controls.current(run.run_id)
        if control.user_paused and not agent_pause_exempt:
            return await self._transition(
                run,
                WorkflowRunStatus.BLOCKED,
                event_type="workflow_blocked_user_pause",
                block_reason=WorkflowBlockReason.USER_PAUSED,
            )
        if control.hard_risk_blocked:
            return await self._transition(
                run,
                WorkflowRunStatus.BLOCKED,
                event_type="workflow_blocked_hard_risk",
                block_reason=WorkflowBlockReason.HARD_RISK,
            )
        return run

    async def _apply_runtime_control(
        self,
        run: WorkflowRun,
        *,
        agent_pause_exempt: bool,
    ) -> WorkflowRun:
        control = self._controls.current(run.run_id)
        if control.hard_risk_blocked:
            return await self._transition(
                run,
                WorkflowRunStatus.BLOCKED,
                event_type="workflow_blocked_hard_risk",
                block_reason=WorkflowBlockReason.HARD_RISK,
            )
        if not control.user_paused or agent_pause_exempt:
            return run
        requested = await self._transition(
            run,
            WorkflowRunStatus.CANCEL_REQUESTED,
            event_type="workflow_cancel_requested",
            cancellation_reason=WorkflowCancellationReason.USER_PAUSED,
        )
        cancelling = await self._transition(
            requested,
            WorkflowRunStatus.CANCELLING,
            event_type="workflow_cancelling",
            cancellation_reason=WorkflowCancellationReason.USER_PAUSED,
        )
        return await self._transition(
            cancelling,
            WorkflowRunStatus.CANCELLED,
            event_type="workflow_cancelled",
            cancellation_reason=WorkflowCancellationReason.USER_PAUSED,
        )

    async def expire_if_inputs_changed(
        self,
        *,
        run_id: str,
        current_input_versions: tuple[VersionReference, ...],
    ) -> WorkflowRun:
        run = await self._require_run(run_id)
        expired = run.expire_if_inputs_changed(
            current_input_versions,
            audit_reference=self._audit(run, "inputs_changed"),
        )
        if expired is run:
            return run
        return await self._save(
            expired,
            expected_revision=run.revision,
            event_type="workflow_inputs_expired",
            payload={
                "current_input_versions": [
                    item.model_dump(mode="json")
                    for item in current_input_versions
                ]
            },
        )

    async def _transition(
        self,
        run: WorkflowRun,
        status: WorkflowRunStatus,
        *,
        event_type: str,
        trade_eligible: bool | None = None,
        block_reason: WorkflowBlockReason | None = None,
        cancellation_reason: WorkflowCancellationReason | None = None,
        final_artifact: VersionReference | None = None,
        errors: tuple[str, ...] | None = None,
        payload: dict[str, object] | None = None,
    ) -> WorkflowRun:
        transitioned = run.transition(
            status,
            audit_reference=self._audit(run, event_type),
            trade_eligible=trade_eligible,
            block_reason=block_reason,
            cancellation_reason=cancellation_reason,
            final_artifact=final_artifact,
            errors=errors,
        )
        return await self._save(
            transitioned,
            expected_revision=run.revision,
            event_type=event_type,
            payload={} if payload is None else payload,
        )

    async def _save(
        self,
        run: WorkflowRun,
        *,
        expected_revision: int,
        event_type: str,
        payload: dict[str, object],
    ) -> WorkflowRun:
        return await self._repository.compare_and_append(
            run=run,
            expected_revision=expected_revision,
            event_type=event_type,
            event_payload=payload,
            outbox_topic=f"workflow.{event_type}",
        )

    def _audit(self, run: WorkflowRun, suffix: str) -> AuditReference:
        now = self._clock.now()
        if now <= run.audit_reference.recorded_at:
            now = run.audit_reference.recorded_at + timedelta(microseconds=1)
        return AuditReference(
            audit_id=f"workflow:{run.run_id}:{run.revision + 1}:{suffix}"[:160],
            actor_id="workflow-executor",
            recorded_at=now,
        )

    def _next_execution_audit_id(self, run_id: str) -> str:
        self._execution_audit_sequence += 1
        return (
            f"workflow:{run_id}:execution:{self._execution_audit_sequence}"
        )[:160]

    async def _require_run(self, run_id: str) -> WorkflowRun:
        run = await self._repository.get(run_id)
        if run is None:
            raise LookupError(f"workflow run does not exist: {run_id}")
        return run

    @staticmethod
    def _validate_plan_binding(
        run: WorkflowRun,
        plan: TaskPlan,
        *,
        owner_id: str,
    ) -> None:
        if plan.owner_id != owner_id:
            raise ValueError("TaskPlan owner differs from persisted workflow owner")
        if run.workflow_key != plan.workflow_key.value:
            raise ValueError("TaskPlan workflow key differs from persisted run")
        if run.workflow_version != plan.workflow_version:
            raise ValueError("TaskPlan workflow version differs from persisted run")
        if run.input_versions != tuple(
            sorted(
                plan.input_versions,
                key=lambda item: (
                    item.object_type,
                    item.object_id,
                    item.version,
                ),
            )
        ):
            raise ValueError("TaskPlan inputs differ from persisted run")
