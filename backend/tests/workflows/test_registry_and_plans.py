from __future__ import annotations

import unittest

from pydantic import ValidationError

from finance_god.agents.catalog import AgentGovernanceCatalog
from finance_god.agents.contracts import (
    NodeRequirement,
    WorkflowCallMode,
    WorkflowKey,
)
from finance_god.domain.models import VersionReference
from finance_god.orchestration.task_plans import (
    DynamicTaskPlanValidator,
    TaskPlan,
    TaskPlanFactory,
)
from finance_god.orchestration.workflow_registry import (
    DETERMINISTIC_SERVICE_POLICIES,
    FormalWorkflowRegistry,
    WorkflowNodeDefinition,
    WorkflowNodeKind,
)


INPUT = (
    VersionReference(
        object_type="snapshot",
        object_id="XNAS:AAPL",
        version="v1",
    ),
)

EXPECTED = {
    WorkflowKey.COMPANY_RESEARCH: ("WF-CR-01", "ResearchMemo"),
    WorkflowKey.MARKET_CONTEXT: ("WF-MC-01", "MarketContext"),
    WorkflowKey.PORTFOLIO_STRESS: ("WF-PS-01", "PortfolioRiskReview"),
    WorkflowKey.STRATEGY_VALIDATION: (
        "WF-SV-01",
        "StrategyValidationDossier",
    ),
    WorkflowKey.REVIEW_ONLY: ("WF-RO-01", "ReviewOnlyMemo"),
    WorkflowKey.DATA_QUALITY_REVIEW: ("WF-DQ-01", "DataQualityReport"),
    WorkflowKey.FUND_RESEARCH: ("WF-FR-01", "FundResearchReport"),
    WorkflowKey.PORTFOLIO_CONSTRUCTION: ("WF-PC-01", "PortfolioProposal"),
    WorkflowKey.TRADE_PLAN_GENERATION: ("WF-TP-01", "TradePlan"),
    WorkflowKey.ORDER_REVIEW: ("WF-OR-01", "OrderReviewMemo"),
    WorkflowKey.SIMULATION_EXECUTION: ("WF-SE-01", "ExecutionRun"),
    WorkflowKey.POST_TRADE_REVIEW: ("WF-PR-01", "TradeReview"),
    WorkflowKey.EVENT_IMPACT: ("WF-EI-01", "EventImpactReport"),
    WorkflowKey.CROSS_MARKET_ANALYSIS: ("WF-CM-01", "CrossMarketReport"),
    WorkflowKey.STRATEGY_MONITORING: ("WF-SM-01", "StrategyMonitorReport"),
}


class FormalWorkflowRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = AgentGovernanceCatalog()
        self.registry = FormalWorkflowRegistry.build_default(self.catalog)

    def test_registry_has_exactly_the_fifteen_prd_workflows(self) -> None:
        self.assertEqual(set(self.registry.as_mapping()), set(WorkflowKey))
        self.assertEqual(len(self.registry.list()), 15)
        for key, (prd_id, artifact) in EXPECTED.items():
            with self.subTest(workflow=key.value):
                definition = self.registry.get(key)
                self.assertEqual(definition.prd_id, prd_id)
                self.assertEqual(definition.final_artifact_type, artifact)
                self.assertTrue(definition.core_stages)
                self.assertTrue(
                    any(node.is_quality_gate for node in definition.nodes)
                )
                self.assertEqual(
                    len([node for node in definition.nodes if node.is_finalizer]),
                    1,
                )

    def test_agent_sets_come_only_from_governance_catalog(self) -> None:
        for definition in self.registry.list():
            expected = {
                entry.agent_id
                for entry in self.catalog.list()
                if entry.declared_call_mode(definition.workflow_key)
                is WorkflowCallMode.MANDATORY
            }
            actual = {
                agent_id
                for node in definition.nodes
                for agent_id in node.agent_ids
            }
            self.assertEqual(actual, expected)

    def test_nontrading_workflows_cannot_be_trade_eligible(self) -> None:
        self.assertFalse(
            self.registry.get(WorkflowKey.REVIEW_ONLY).allows_trade_eligibility
        )

    def test_only_simulation_execution_can_write_simulated_trade_facts(self) -> None:
        for definition in self.registry.list():
            writers = [node for node in definition.nodes if node.writes_trade_facts]
            if definition.workflow_key is WorkflowKey.SIMULATION_EXECUTION:
                self.assertTrue(writers)
            else:
                self.assertEqual(writers, [])
        writable_services = {
            service_id
            for service_id, policy in DETERMINISTIC_SERVICE_POLICIES.items()
            if policy.may_write_trade_facts
        }
        self.assertEqual(
            writable_services,
            {
                "simulation.order_accept",
                "simulation.match",
                "simulation.ledger_update",
            },
        )
        self.assertFalse(
            any(
                token in service_id.lower()
                for service_id in DETERMINISTIC_SERVICE_POLICIES
                for token in ("live", "broker", "ctp")
            )
        )
        self.assertFalse(
            self.registry.get(
                WorkflowKey.DATA_QUALITY_REVIEW
            ).allows_trade_eligibility
        )


class DynamicTaskPlanSecurityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = AgentGovernanceCatalog()
        self.registry = FormalWorkflowRegistry.build_default(self.catalog)
        self.factory = TaskPlanFactory(self.catalog, self.registry)
        self.validator = DynamicTaskPlanValidator(self.catalog, self.registry)
        self.base = self.factory.formal(
            plan_id="dynamic-base",
            owner_id="user-1",
            workflow_key=WorkflowKey.COMPANY_RESEARCH,
            input_versions=INPUT,
            route_reason="dynamic validation",
        )

    def test_unknown_dependency_and_cycle_are_rejected(self) -> None:
        nodes = list(self.base.nodes)
        nodes[0] = nodes[0].model_copy(
            update={"dependencies": ("does_not_exist",)}
        )
        with self.assertRaisesRegex(ValidationError, "unknown dependencies"):
            TaskPlan(**{**self.base.model_dump(), "nodes": tuple(nodes)})

        first, second = self.base.nodes[:2]
        cyclic = (
            first.model_copy(update={"dependencies": (second.node_id,)}),
            second.model_copy(update={"dependencies": (first.node_id,)}),
            *self.base.nodes[2:],
        )
        with self.assertRaisesRegex(ValidationError, "cycle"):
            TaskPlan(**{**self.base.model_dump(), "nodes": cyclic})

    def test_node_limit_is_strict(self) -> None:
        prototype = self.base.nodes[0]
        nodes = tuple(
            prototype.model_copy(update={"node_id": f"agent_{index}"})
            for index in range(65)
        )
        with self.assertRaises(ValidationError):
            TaskPlan(**{**self.base.model_dump(), "nodes": nodes})

    def test_plan_requires_exactly_one_finalizer_and_a_quality_gate(self) -> None:
        without_finalizer = tuple(
            node.model_copy(update={"is_finalizer": False})
            for node in self.base.nodes
        )
        with self.assertRaisesRegex(ValidationError, "exactly one finalizer"):
            TaskPlan(
                **{**self.base.model_dump(), "nodes": without_finalizer}
            )

        duplicate_finalizer = list(self.base.nodes)
        duplicate_finalizer[0] = duplicate_finalizer[0].model_copy(
            update={"is_finalizer": True}
        )
        with self.assertRaisesRegex(ValidationError, "exactly one finalizer"):
            TaskPlan(
                **{**self.base.model_dump(), "nodes": tuple(duplicate_finalizer)}
            )

        without_quality = tuple(
            node.model_copy(update={"is_quality_gate": False})
            for node in self.base.nodes
        )
        with self.assertRaisesRegex(ValidationError, "quality gate"):
            TaskPlan(**{**self.base.model_dump(), "nodes": without_quality})

    def test_denied_agent_is_rejected(self) -> None:
        denied = next(
            entry
            for entry in self.catalog.list()
            if entry.declared_call_mode(WorkflowKey.COMPANY_RESEARCH)
            is WorkflowCallMode.DENIED
        )
        malicious = self._agent_node(
            node_id="denied_agent",
            agent_id=denied.agent_id,
        )
        plan = self._with_extra(malicious)
        with self.assertRaisesRegex(ValueError, "denied"):
            self.validator.validate(plan)

    def test_agent_trade_write_tool_is_rejected(self) -> None:
        allowed_agent = self.base.nodes[0].agent_ids[0]
        malicious = self._agent_node(
            node_id="cash_writer",
            agent_id=allowed_agent,
            tools=frozenset({"cash.write"}),
        )
        plan = self._with_extra(
            malicious,
            allowed_tools=self.base.allowed_tools | {"cash.write"},
        )
        with self.assertRaisesRegex(ValueError, "trade-write"):
            self.validator.validate(plan)

    def test_unknown_service_is_rejected(self) -> None:
        source = next(node for node in self.base.nodes if node.service_id)
        malicious = source.model_copy(
            update={
                "node_id": "unknown_service",
                "service_id": "unknown.service",
                "is_quality_gate": False,
                "is_finalizer": False,
                "dependencies": (),
            }
        )
        plan = self._with_extra(malicious)
        with self.assertRaisesRegex(ValueError, "unknown deterministic service"):
            self.validator.validate(plan)

    def test_live_external_action_is_hard_denied(self) -> None:
        source = next(
            node
            for node in self.base.nodes
            if node.service_id == "workflow.input_quality_gate"
        )
        malicious = source.model_copy(
            update={
                "node_id": "live_broker_submit",
                "dependencies": (),
                "external_action_allowlist": frozenset({"broker.order.submit"}),
                "is_quality_gate": False,
            }
        )
        plan = self._with_extra(
            malicious,
            allowed_external_actions=frozenset({"broker.order.submit"}),
        )
        with self.assertRaisesRegex(ValueError, "action allowlist exceeded"):
            self.validator.validate(plan)

    def test_trade_fact_writer_is_denied_outside_simulation_execution(self) -> None:
        source = next(
            node
            for node in self.registry.get(
                WorkflowKey.SIMULATION_EXECUTION
            ).nodes
            if node.service_id == "simulation.match"
        )
        malicious = source.model_copy(
            update={
                "node_id": "parallel_trade_writer",
                "dependencies": (),
            }
        )
        plan = self._with_extra(
            malicious,
            allowed_tools=self.base.allowed_tools | source.tool_allowlist,
            allowed_external_actions=source.external_action_allowlist,
        )
        with self.assertRaisesRegex(
            ValueError,
            "only simulation execution may write trade facts",
        ):
            self.validator.validate(plan)

    def _agent_node(
        self,
        *,
        node_id: str,
        agent_id: str,
        tools: frozenset[str] = frozenset(),
    ) -> WorkflowNodeDefinition:
        return WorkflowNodeDefinition(
            node_id=node_id,
            title="Malicious planner output",
            kind=WorkflowNodeKind.AGENT,
            agent_ids=(agent_id,),
            dependencies=(),
            requirement=NodeRequirement.NON_BLOCKING,
            timeout_seconds=1,
            retry_budget=self.base.nodes[0].retry_budget,
            tool_allowlist=tools,
        )

    def _with_extra(
        self,
        node: WorkflowNodeDefinition,
        *,
        allowed_tools: frozenset[str] | None = None,
        allowed_external_actions: frozenset[str] | None = None,
    ) -> TaskPlan:
        finalizer_index = next(
            index
            for index, item in enumerate(self.base.nodes)
            if item.is_finalizer
        )
        nodes = list(self.base.nodes)
        finalizer = nodes[finalizer_index]
        nodes[finalizer_index] = finalizer.model_copy(
            update={
                "dependencies": (*finalizer.dependencies, node.node_id),
            }
        )
        nodes.insert(finalizer_index, node)
        return TaskPlan(
            **{
                **self.base.model_dump(),
                "nodes": tuple(nodes),
                "maximum_total_attempts": (
                    self.base.maximum_total_attempts
                    + node.retry_budget.total_attempt_limit
                ),
                "allowed_tools": (
                    self.base.allowed_tools
                    if allowed_tools is None
                    else allowed_tools
                ),
                "allowed_external_actions": (
                    self.base.allowed_external_actions
                    if allowed_external_actions is None
                    else allowed_external_actions
                ),
                "dynamic": True,
            }
        )


if __name__ == "__main__":
    unittest.main()
