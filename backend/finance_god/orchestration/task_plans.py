"""Validated immutable TaskPlan contracts for formal and dynamic workflows."""

from __future__ import annotations

import hashlib
from typing import Self

from pydantic import Field, model_validator

from finance_god.agents.catalog import (
    TRADE_WRITE_TOOLS,
    AgentGovernanceCatalog,
)
from finance_god.agents.contracts import (
    NodeRequirement,
    OrderReviewMode,
    RequirementContext,
    WorkflowCallMode,
    WorkflowKey,
    WorkflowSelectionContext,
)
from finance_god.domain.models import VersionReference, WorkflowDependencySnapshot

from .workflow_registry import (
    DETERMINISTIC_SERVICE_POLICIES,
    MAX_WORKFLOW_ATTEMPTS,
    MAX_WORKFLOW_DURATION_SECONDS,
    FormalWorkflowRegistry,
    FrozenModel,
    WorkflowDefinition,
    WorkflowNodeDefinition,
    WorkflowNodeKind,
)


class TaskPlan(FrozenModel):
    plan_id: str = Field(pattern=r"^[A-Za-z0-9_-]+$", max_length=160)
    version: str = Field(min_length=1, max_length=80)
    owner_id: str = Field(min_length=1, max_length=160)
    workflow_key: WorkflowKey
    workflow_version: str = Field(min_length=1, max_length=80)
    final_artifact_type: str = Field(pattern=r"^[A-Z][A-Za-z0-9]*$")
    nodes: tuple[WorkflowNodeDefinition, ...] = Field(min_length=1, max_length=64)
    input_versions: tuple[VersionReference, ...] = Field(min_length=1)
    workflow_dependencies: tuple[WorkflowDependencySnapshot, ...] = ()
    acceptance_criteria: tuple[str, ...] = Field(min_length=1, max_length=32)
    termination_conditions: tuple[str, ...] = Field(min_length=1, max_length=16)
    maximum_feedback_rounds: int = Field(ge=0, le=3)
    maximum_total_attempts: int = Field(ge=1, le=MAX_WORKFLOW_ATTEMPTS)
    maximum_duration_seconds: int = Field(
        ge=1,
        le=MAX_WORKFLOW_DURATION_SECONDS,
    )
    allowed_tools: frozenset[str]
    allowed_resources: frozenset[str]
    allowed_external_actions: frozenset[str]
    route_reason: str = Field(min_length=1, max_length=500)
    automatic_trade_chain: bool = False
    agent_pause_exempt: bool = False
    dynamic: bool = False

    @model_validator(mode="after")
    def validate_plan_invariants(self) -> Self:
        if len({node.node_id for node in self.nodes}) != len(self.nodes):
            raise ValueError("TaskPlan node IDs must be unique")
        node_ids = {node.node_id for node in self.nodes}
        for node in self.nodes:
            missing = set(node.dependencies) - node_ids
            if missing:
                raise ValueError(
                    f"{node.node_id} has unknown dependencies: {sorted(missing)}"
                )
        _require_acyclic(self.nodes)
        if len([node for node in self.nodes if node.is_finalizer]) != 1:
            raise ValueError("TaskPlan requires exactly one finalizer")
        if not any(node.is_quality_gate for node in self.nodes):
            raise ValueError("TaskPlan requires at least one quality gate")
        if len(set(self.input_versions)) != len(self.input_versions):
            raise ValueError("TaskPlan input versions must be unique")
        if sum(node.retry_budget.total_attempt_limit for node in self.nodes) > (
            self.maximum_total_attempts
        ):
            raise ValueError("TaskPlan node attempt budgets exceed total limit")
        if self.automatic_trade_chain and not self.workflow_dependencies:
            raise ValueError("automatic trade TaskPlan requires fixed dependencies")
        if self.agent_pause_exempt and (
            self.workflow_key
            not in {
                WorkflowKey.ORDER_REVIEW,
                WorkflowKey.REVIEW_ONLY,
                WorkflowKey.DATA_QUALITY_REVIEW,
            }
            or any(node.kind is WorkflowNodeKind.AGENT for node in self.nodes)
        ):
            raise ValueError(
                "Agent pause exemption requires deterministic-only order_review"
            )
        if any(
            node.tool_allowlist - self.allowed_tools
            or node.resource_allowlist - self.allowed_resources
            or node.external_action_allowlist - self.allowed_external_actions
            for node in self.nodes
        ):
            raise ValueError("TaskPlan node exceeds the fixed plan allowlists")
        return self

    @property
    def reference(self) -> VersionReference:
        return VersionReference(
            object_type="task_plan",
            object_id=self.plan_id,
            version=self.version,
        )

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


class DynamicTaskPlanValidator:
    """Validates Planner output without duplicating Agent capability rules."""

    def __init__(
        self,
        catalog: AgentGovernanceCatalog,
        registry: FormalWorkflowRegistry,
    ) -> None:
        self._catalog = catalog
        self._registry = registry

    def validate(
        self,
        plan: TaskPlan,
        *,
        selection_context: WorkflowSelectionContext | None = None,
    ) -> TaskPlan:
        definition = self._registry.get(plan.workflow_key)
        if plan.workflow_version != definition.version:
            raise ValueError("TaskPlan workflow version differs from registry")
        if plan.final_artifact_type != definition.final_artifact_type:
            raise ValueError("TaskPlan final artifact differs from registry contract")
        actual_agents = {
            agent_id for node in plan.nodes for agent_id in node.agent_ids
        }
        mandatory = {
            entry.agent_id
            for entry in self._catalog.list()
            if entry.declared_call_mode(plan.workflow_key)
            is WorkflowCallMode.MANDATORY
        }
        missing = mandatory - actual_agents
        if missing:
            raise ValueError(f"TaskPlan omits mandatory Agents: {sorted(missing)}")
        for node in plan.nodes:
            if node.kind is WorkflowNodeKind.AGENT:
                self._validate_agent_node(plan, node, selection_context)
            else:
                self._validate_service_node(plan, node)
        return plan

    def _validate_agent_node(
        self,
        plan: TaskPlan,
        node: WorkflowNodeDefinition,
        context: WorkflowSelectionContext | None,
    ) -> None:
        if node.tool_allowlist & TRADE_WRITE_TOOLS:
            raise ValueError("Agent node requests a prohibited trade-write tool")
        for agent_id in node.agent_ids:
            entry = self._catalog.get(agent_id)
            mode = entry.resolve_call_mode(plan.workflow_key, context)
            if mode is WorkflowCallMode.DENIED:
                raise ValueError(
                    f"{agent_id} is denied for {plan.workflow_key.value}"
                )
            if not node.tool_allowlist.issubset(entry.tool_allowlist):
                raise ValueError(f"{agent_id} tool allowlist exceeded")
            if not node.data_permissions.issubset(
                entry.data_permission_allowlist
            ):
                raise ValueError(f"{agent_id} data permissions exceeded")
            capability = entry.vendor_capability
            if capability is not None and not capability.required_resources.issubset(
                plan.allowed_resources
            ):
                raise ValueError(f"{agent_id} required resource is not approved")

    @staticmethod
    def _validate_service_node(
        plan: TaskPlan,
        node: WorkflowNodeDefinition,
    ) -> None:
        policy = DETERMINISTIC_SERVICE_POLICIES.get(node.service_id or "")
        if policy is None:
            raise ValueError(f"unknown deterministic service: {node.service_id}")
        if not node.tool_allowlist.issubset(policy.tool_allowlist):
            raise ValueError("deterministic service tool allowlist exceeded")
        if not node.resource_allowlist.issubset(policy.resource_allowlist):
            raise ValueError("deterministic service resource allowlist exceeded")
        if not node.external_action_allowlist.issubset(
            policy.external_action_allowlist
        ):
            raise ValueError("deterministic service action allowlist exceeded")
        if node.writes_trade_facts and not policy.may_write_trade_facts:
            raise ValueError("service cannot write trade facts")
        if (
            node.writes_trade_facts
            and plan.workflow_key is not WorkflowKey.SIMULATION_EXECUTION
        ):
            raise ValueError("only simulation execution may write trade facts")


class TaskPlanFactory:
    def __init__(
        self,
        catalog: AgentGovernanceCatalog,
        registry: FormalWorkflowRegistry,
    ) -> None:
        self._catalog = catalog
        self._registry = registry

    def formal(
        self,
        *,
        plan_id: str,
        owner_id: str,
        workflow_key: WorkflowKey,
        input_versions: tuple[VersionReference, ...],
        workflow_dependencies: tuple[WorkflowDependencySnapshot, ...] = (),
        route_reason: str,
        order_review_mode: OrderReviewMode | None = None,
        suppress_agents: bool = False,
        paused_manual_fallback: bool = False,
        automatic_trade_chain: bool = False,
    ) -> TaskPlan:
        valid_manual_order_suppression = (
            workflow_key is WorkflowKey.ORDER_REVIEW
            and order_review_mode is OrderReviewMode.MANUAL
        )
        valid_fallback_suppression = (
            paused_manual_fallback
            and workflow_key
            in {WorkflowKey.REVIEW_ONLY, WorkflowKey.DATA_QUALITY_REVIEW}
        )
        if suppress_agents and not (
            valid_manual_order_suppression or valid_fallback_suppression
        ):
            raise ValueError(
                "Agent suppression requires manual order_review or its paused fallback"
            )
        definition = self._registry.get(workflow_key)
        nodes = self._variant_nodes(
            definition,
            order_review_mode=order_review_mode,
            suppress_agents=suppress_agents,
        )
        return TaskPlan(
            plan_id=plan_id,
            version=_plan_version(
                definition,
                nodes,
                input_versions,
                workflow_dependencies,
                owner_id,
            ),
            owner_id=owner_id,
            workflow_key=workflow_key,
            workflow_version=definition.version,
            final_artifact_type=definition.final_artifact_type,
            nodes=nodes,
            input_versions=input_versions,
            workflow_dependencies=workflow_dependencies,
            acceptance_criteria=(
                "全部 required 节点完成。",
                "确定性质量门通过。",
                "最终产物绑定全部输入与贡献版本。",
            ),
            termination_conditions=(
                "required 节点失败或超时。",
                "工作流总次数或总时长耗尽。",
                "用户暂停、硬风控或输入版本变化。",
            ),
            maximum_feedback_rounds=3,
            maximum_total_attempts=sum(
                node.retry_budget.total_attempt_limit for node in nodes
            ),
            maximum_duration_seconds=definition.maximum_duration_seconds,
            allowed_tools=frozenset(
                tool for node in nodes for tool in node.tool_allowlist
            ),
            allowed_resources=frozenset(
                resource for node in nodes for resource in node.resource_allowlist
            ),
            allowed_external_actions=frozenset(
                action
                for node in nodes
                for action in node.external_action_allowlist
            ),
            route_reason=route_reason,
            automatic_trade_chain=automatic_trade_chain,
            agent_pause_exempt=suppress_agents,
            dynamic=False,
        )

    def _variant_nodes(
        self,
        definition: WorkflowDefinition,
        *,
        order_review_mode: OrderReviewMode | None,
        suppress_agents: bool,
    ) -> tuple[WorkflowNodeDefinition, ...]:
        if not suppress_agents:
            return tuple(
                self._with_requirement(
                    node,
                    workflow_key=definition.workflow_key,
                    order_review_mode=order_review_mode,
                )
                for node in definition.nodes
            )
        retained = tuple(
            node
            for node in definition.nodes
            if node.kind is WorkflowNodeKind.DETERMINISTIC_SERVICE
        )
        rewritten: list[WorkflowNodeDefinition] = []
        previous: str | None = None
        for node in retained:
            dependencies = () if previous is None else (previous,)
            rewritten.append(
                node.model_copy(update={"dependencies": dependencies})
            )
            previous = node.node_id
        return tuple(rewritten)

    def _with_requirement(
        self,
        node: WorkflowNodeDefinition,
        *,
        workflow_key: WorkflowKey,
        order_review_mode: OrderReviewMode | None,
    ) -> WorkflowNodeDefinition:
        if node.kind is not WorkflowNodeKind.AGENT:
            return node
        requirement = NodeRequirement.REQUIRED
        for agent_id in node.agent_ids:
            entry = self._catalog.get(agent_id)
            resolved = entry.requirement_for(
                workflow_key,
                RequirementContext(order_review_mode=order_review_mode),
            )
            if resolved is NodeRequirement.NON_BLOCKING:
                requirement = NodeRequirement.NON_BLOCKING
        return node.model_copy(update={"requirement": requirement})


def _plan_version(
    definition: WorkflowDefinition,
    nodes: tuple[WorkflowNodeDefinition, ...],
    input_versions: tuple[VersionReference, ...],
    dependencies: tuple[WorkflowDependencySnapshot, ...],
    owner_id: str,
) -> str:
    material = "|".join(
        (
            definition.version,
            definition.workflow_key.value,
            owner_id,
            *(node.model_dump_json() for node in nodes),
            *(
                f"{item.object_type}:{item.object_id}:{item.version}"
                for item in input_versions
            ),
            *(
                f"{item.run_reference.object_type}:"
                f"{item.run_reference.object_id}:"
                f"{item.run_reference.version}"
                for item in dependencies
            ),
        )
    )
    return hashlib.sha256(material.encode()).hexdigest()


def _require_acyclic(nodes: tuple[WorkflowNodeDefinition, ...]) -> None:
    dependencies = {node.node_id: set(node.dependencies) for node in nodes}
    remaining = set(dependencies)
    while remaining:
        ready = {
            node_id
            for node_id in remaining
            if not (dependencies[node_id] & remaining)
        }
        if not ready:
            raise ValueError("TaskPlan DAG contains a cycle")
        remaining -= ready
