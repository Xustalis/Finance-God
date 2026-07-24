from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError, replace
from typing import Any

from research_runtime import AgentRegistry, ExecutionProfile

from finance_god.agents import (
    AGENT_INPUT_CONTRACT_ID,
    AGENT_OUTPUT_CONTRACT_ID,
    CONTRACT_REGISTRY,
    PLANNER_ID,
    TRADE_WRITE_TOOLS,
    AgentGovernanceCatalog,
    AgentGovernanceEntry,
    AgentInputEnvelope,
    AgentOutputEnvelope,
    EvidenceBoundStatement,
    EvidenceReference,
    ExecutionType,
    FailureKind,
    ImpactClass,
    NodeRequirement,
    OrderReviewMode,
    RequirementContext,
    SelectionSignal,
    WorkflowCallMode,
    WorkflowKey,
    WorkflowSelectionContext,
)

from .prd_catalog_fixture import (
    PRD_AGENT_MATRIX,
    PRD_CONDITION_REQUIREMENTS,
    WORKFLOWS,
)


def _satisfying_context(agent_id: str, condition_id: str) -> WorkflowSelectionContext:
    signals: set[SelectionSignal] = set()
    asset_kinds: set[str] = set()
    resources: set[str] = set()
    data_capabilities: set[str] = set()
    signal_by_condition = {
        "issuer_or_underlying": SelectionSignal.ISSUER_OR_UNDERLYING,
        "qualified_sentiment_evidence": SelectionSignal.QUALIFIED_SENTIMENT_EVIDENCE,
        "requires_debate": SelectionSignal.REQUIRES_DEBATE,
        "requires_code_implementation": SelectionSignal.REQUIRES_CODE_IMPLEMENTATION,
        "requires_non_alpha_implementation": (
            SelectionSignal.REQUIRES_NON_ALPHA_IMPLEMENTATION
        ),
        "technical_fault": SelectionSignal.TECHNICAL_FAULT,
        "ai_model_or_quality_issue": SelectionSignal.AI_MODEL_OR_QUALITY_ISSUE,
        "requires_report_review": SelectionSignal.REQUIRES_REPORT_REVIEW,
        "requires_ui_tagline": SelectionSignal.REQUIRES_UI_TAGLINE,
        "complex_panda_trading_development": (
            SelectionSignal.COMPLEX_PANDA_TRADING_DEVELOPMENT
        ),
    }
    if condition_id in signal_by_condition:
        signals.add(signal_by_condition[condition_id])
    if condition_id in {
        "requires_code_implementation",
        "requires_non_alpha_implementation",
    }:
        resources.add("workspace")
    if condition_id == "equity_fmp_workspace_available":
        asset_kinds.add("equity")
        resources.update({"fmp", "workspace"})
    if condition_id == "option_data_available":
        data_capabilities.update(
            {"option_implied_volatility", "option_underlying_volatility"}
        )
    if condition_id == "complex_panda_trading_development":
        resources.update({"workspace", "panda_trading"})
    if condition_id == "isolated_ssquant_simulation_available":
        resources.update({"workspace", "ssquant_simulation"})
    return WorkflowSelectionContext(
        selected_agent_ids=frozenset({agent_id}),
        signals=frozenset(signals),
        asset_kinds=frozenset(asset_kinds),
        available_resources=frozenset(resources),
        data_capabilities=frozenset(data_capabilities),
    )


def _valid_input(entry: AgentGovernanceEntry) -> AgentInputEnvelope:
    return AgentInputEnvelope(
        agent_id=entry.agent_id,
        contract_id=entry.input_contract_id,
        schema_version="1",
        run_id="run-1",
        workflow_id="company_research",
        workflow_version="v1",
        input_version="input-v1",
        evidence=(EvidenceReference("E1", "pandadata", "v1", True),),
        role_payload={"subject": "示例公司"},
    )


def _valid_output(entry: AgentGovernanceEntry) -> AgentOutputEnvelope:
    return AgentOutputEnvelope(
        agent_id=entry.agent_id,
        contract_id=entry.output_contract_id,
        schema_version="1",
        run_id="run-1",
        artifact_id="artifact-1",
        output_version="v1",
        input_version="input-v1",
        facts=(EvidenceBoundStatement("收入增长。", ("E1",)),),
        inferences=(),
        recommendations=(EvidenceBoundStatement("等待用户审阅。", ("E1",)),),
        unknowns=("未来收入持续性未知。",),
        invalidation_conditions=("新财报修正收入。",),
        role_payload={"analysis": "基本面事实与限制"},
    )


class AgentGovernanceCatalogTest(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = AgentGovernanceCatalog()

    def test_catalog_is_43_immutable_vendor_snapshots_plus_planner(self) -> None:
        identifiers = {entry.agent_id for entry in self.catalog.list()}

        self.assertEqual(len(identifiers), 44)
        self.assertEqual(
            identifiers - {PLANNER_ID},
            {definition.agent_id for definition in AgentRegistry().list()},
        )
        self.assertIsNone(self.catalog.get(PLANNER_ID).vendor_capability)
        for definition in AgentRegistry().list():
            entry = self.catalog.get(definition.agent_id)
            capability = entry.vendor_capability
            self.assertIsNotNone(capability)
            assert capability is not None
            self.assertEqual(capability.agent_id, definition.agent_id)
            self.assertFalse(hasattr(entry, "vendor_definition"))

    def test_independent_prd_fixture_verifies_all_660_matrix_cells(self) -> None:
        self.assertEqual(
            set(PRD_AGENT_MATRIX), {entry.agent_id for entry in self.catalog.list()}
        )
        self.assertEqual(set(WORKFLOWS), {workflow.value for workflow in WorkflowKey})
        checked = 0
        for agent_id, (mandatory, conditional, _) in PRD_AGENT_MATRIX.items():
            entry = self.catalog.get(agent_id)
            for workflow in WORKFLOWS:
                expected = WorkflowCallMode.DENIED
                if workflow in mandatory:
                    expected = WorkflowCallMode.MANDATORY
                elif workflow in conditional:
                    expected = WorkflowCallMode.CONDITIONAL
                self.assertEqual(
                    entry.declared_call_mode(workflow),
                    expected,
                    f"{agent_id}/{workflow}",
                )
                checked += 1
        self.assertEqual(checked, 44 * 15)

    def test_every_conditional_cell_has_exact_prd_condition_and_default_denies(
        self,
    ) -> None:
        checked = 0
        for agent_id, (_, conditional, condition_id) in PRD_AGENT_MATRIX.items():
            entry = self.catalog.get(agent_id)
            for workflow in conditional:
                decision = entry.workflow_matrix[WorkflowKey(workflow)]
                rule = decision.conditional_rule
                self.assertIsNotNone(rule)
                assert rule is not None
                self.assertEqual(rule.condition_id, condition_id)
                expected = PRD_CONDITION_REQUIREMENTS[condition_id]
                actual = (
                    frozenset(signal.value for signal in rule.required_signals),
                    rule.required_asset_kinds,
                    rule.required_resources,
                    rule.required_data_capabilities,
                )
                self.assertEqual(actual, expected)
                self.assertFalse(entry.is_allowed(workflow))
                if condition_id != "planner_selected":
                    self.assertFalse(
                        entry.is_allowed(
                            workflow,
                            WorkflowSelectionContext(
                                selected_agent_ids=frozenset({agent_id})
                            ),
                        )
                    )
                self.assertTrue(
                    entry.is_allowed(
                        workflow,
                        _satisfying_context(agent_id, condition_id),
                    )
                )
                checked += 1
        self.assertGreater(checked, 0)

    def test_unselected_agent_and_unknown_workflow_are_denied(self) -> None:
        market = self.catalog.get("tradingagents:market_analyst")
        context = WorkflowSelectionContext(
            selected_agent_ids=frozenset({"tradingagents:news_analyst"})
        )

        self.assertFalse(market.is_allowed(WorkflowKey.ORDER_REVIEW, context))
        self.assertEqual(
            market.resolve_call_mode("not_a_formal_workflow", context),
            WorkflowCallMode.DENIED,
        )
        default_ids = {
            entry.agent_id
            for entry in self.catalog.for_workflow(WorkflowKey.ORDER_REVIEW)
        }
        self.assertNotIn("tradingagents:market_analyst", default_ids)
        selected_ids = {
            entry.agent_id
            for entry in self.catalog.for_workflow(
                WorkflowKey.ORDER_REVIEW,
                WorkflowSelectionContext(
                    selected_agent_ids=frozenset({"tradingagents:market_analyst"})
                ),
            )
        }
        self.assertIn("tradingagents:market_analyst", selected_ids)

    def test_ssquant_vendor_actions_and_authorizations_are_explicitly_denied(
        self,
    ) -> None:
        ssquant = self.catalog.get("quantskills:agent-ssquant")
        capability = ssquant.vendor_capability
        actions = frozenset({"ctp_start", "order_cancel", "order_entry"})

        self.assertEqual(ssquant.impact_class, ImpactClass.EXECUTION_FORBIDDEN)
        self.assertIsNotNone(capability)
        assert capability is not None
        self.assertEqual(capability.declared_external_actions, actions)
        self.assertEqual(capability.denied_external_actions, actions)
        self.assertEqual(capability.effective_external_actions, frozenset())
        self.assertEqual(
            dict(capability.declared_authorizations_by_task)["live_trading"],
            actions,
        )
        self.assertEqual(
            dict(capability.denied_authorizations_by_task)["live_trading"],
            actions,
        )
        self.assertEqual(capability.effective_authorizations_by_task, ())
        for action in (*actions, "new_vendor_external_action"):
            self.assertFalse(ssquant.allows_external_action(action))
            self.assertFalse(ssquant.allows_tool(action))

    def test_all_write_tools_and_unknown_permissions_default_deny(self) -> None:
        for entry in self.catalog.list():
            self.assertTrue(TRADE_WRITE_TOOLS.isdisjoint(entry.tool_allowlist))
            self.assertFalse(entry.allows_tool("order.submit"))
            self.assertFalse(entry.allows_tool("unknown.tool"))
            self.assertFalse(entry.allows_data_permission("trading_fact.write"))
            self.assertFalse(entry.allows_external_action("unknown.action"))

    def test_vendor_capability_fingerprint_drift_fails_closed(self) -> None:
        definitions = tuple(
            definition.model_copy(deep=True) for definition in AgentRegistry().list()
        )
        changed = definitions[0].model_copy(
            update={"minimum_profile": ExecutionProfile.WORKSPACE}
        )

        with self.assertRaisesRegex(ValueError, "capability fingerprint drift"):
            AgentGovernanceCatalog((changed, *definitions[1:]))
        with self.assertRaisesRegex(ValueError, "capability fingerprint drift"):
            AgentGovernanceCatalog(definitions[:-1])

    def test_vendor_mutation_after_construction_cannot_change_snapshot(self) -> None:
        definitions = tuple(
            definition.model_copy(deep=True) for definition in AgentRegistry().list()
        )
        catalog = AgentGovernanceCatalog(definitions)
        source = next(
            item for item in definitions if item.agent_id == "quantskills:agent-ssquant"
        )
        source.external_actions.add("new_vendor_external_action")
        snapshot = catalog.get(source.agent_id).vendor_capability

        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertNotIn(
            "new_vendor_external_action", snapshot.declared_external_actions
        )
        with self.assertRaises((AttributeError, FrozenInstanceError)):
            setattr(snapshot, "source", "mutated")

    def test_registered_contracts_are_structured_and_versioned(self) -> None:
        input_contract = CONTRACT_REGISTRY[AGENT_INPUT_CONTRACT_ID]
        output_contract = CONTRACT_REGISTRY[AGENT_OUTPUT_CONTRACT_ID]

        self.assertEqual(input_contract.version, "1")
        self.assertIn("evidence", {field.name for field in input_contract.fields})
        self.assertEqual(
            {
                "facts",
                "inferences",
                "recommendations",
                "unknowns",
                "invalidation_conditions",
                "input_version",
            }
            - {field.name for field in output_contract.fields},
            set(),
        )
        for entry in self.catalog.list():
            self.assertIn(entry.input_contract_id, CONTRACT_REGISTRY)
            self.assertIn(entry.output_contract_id, CONTRACT_REGISTRY)
            role_input = CONTRACT_REGISTRY[entry.input_contract_id]
            role_output = CONTRACT_REGISTRY[entry.output_contract_id]
            self.assertIn("role_inputs", {field.name for field in role_input.fields})
            self.assertIn("role_output", {field.name for field in role_output.fields})
            if entry.agent_id != PLANNER_ID:
                self.assertEqual(
                    role_input.required_role_payload_keys,
                    frozenset({"subject"}),
                )
                self.assertEqual(
                    role_output.required_role_payload_keys,
                    frozenset({"analysis"}),
                )
        self.assertEqual(
            len({entry.input_contract_id for entry in self.catalog.list()}),
            44,
        )
        self.assertEqual(
            len({entry.output_contract_id for entry in self.catalog.list()}),
            44,
        )

    def test_input_contract_rejects_unapproved_or_duplicate_evidence(self) -> None:
        entry = self.catalog.get("tradingagents:fundamentals_analyst")
        approved = EvidenceReference("E1", "pandadata", "v1", True)
        valid = _valid_input(entry)
        CONTRACT_REGISTRY.validate_input(entry, valid)

        with self.assertRaisesRegex(ValueError, "unapproved evidence"):
            AgentInputEnvelope(
                agent_id=entry.agent_id,
                contract_id=entry.input_contract_id,
                schema_version="1",
                run_id="run",
                workflow_id="workflow",
                workflow_version="v1",
                input_version="input-v1",
                evidence=(EvidenceReference("E2", "news", "v1", False),),
                role_payload={"subject": "公司"},
            )
        with self.assertRaisesRegex(ValueError, "unique"):
            AgentInputEnvelope(
                agent_id=entry.agent_id,
                contract_id=entry.input_contract_id,
                schema_version="1",
                run_id="run",
                workflow_id="workflow",
                workflow_version="v1",
                input_version="input-v1",
                evidence=(
                    approved,
                    EvidenceReference(" E1 ", "pandadata", "v1", True),
                ),
                role_payload={"subject": "公司"},
            )

    def test_output_contract_separates_claim_classes_and_back_references_input(
        self,
    ) -> None:
        entry = self.catalog.get("tradingagents:fundamentals_analyst")
        input_envelope = _valid_input(entry)
        output = _valid_output(entry)

        self.assertEqual(output.input_version, "input-v1")
        CONTRACT_REGISTRY.validate_output(entry, output, input_envelope)
        with self.assertRaisesRegex(ValueError, "unavailable evidence"):
            AgentOutputEnvelope(
                agent_id=entry.agent_id,
                contract_id=entry.output_contract_id,
                schema_version="1",
                run_id="run-1",
                artifact_id="artifact-2",
                output_version="v1",
                input_version="input-v1",
                facts=(EvidenceBoundStatement("未知来源事实。", ("E9",)),),
                inferences=(),
                recommendations=(),
                unknowns=("来源未知。",),
                invalidation_conditions=("获得来源后重审。",),
                role_payload={"analysis": "未知来源"},
            ).validate_against(input_envelope)
        with self.assertRaisesRegex(ValueError, "unavailable evidence"):
            AgentOutputEnvelope(
                agent_id=entry.agent_id,
                contract_id=entry.output_contract_id,
                schema_version="1",
                run_id="run-1",
                artifact_id="artifact-3",
                output_version="v1",
                input_version="input-v1",
                facts=(),
                inferences=(),
                recommendations=(EvidenceBoundStatement("建议。", ("E9",)),),
                unknowns=("来源未知。",),
                invalidation_conditions=("获得来源后重审。",),
                role_payload={"analysis": "未知来源"},
            ).validate_against(input_envelope)
        with self.assertRaisesRegex(ValueError, "evidence references"):
            EvidenceBoundStatement("无证据事实。", ())

    def test_planner_contract_allows_no_research_evidence_but_requires_task_plan(
        self,
    ) -> None:
        planner = self.catalog.get(PLANNER_ID)
        planner_input = AgentInputEnvelope(
            agent_id=planner.agent_id,
            contract_id=planner.input_contract_id,
            schema_version="1",
            run_id="run-planner",
            workflow_id="company_research",
            workflow_version="v1",
            input_version="input-planner-v1",
            evidence=(),
            role_payload={
                "user_goal": "研究示例公司",
                "market_asset_context": "A股示例公司",
                "status_context": "Agent可用",
                "data_context": "日线已收盘",
                "resource_context": "Prompt预算可用",
            },
        )
        planner_output = AgentOutputEnvelope(
            agent_id=planner.agent_id,
            contract_id=planner.output_contract_id,
            schema_version="1",
            run_id="run-planner",
            artifact_id="task-plan-1",
            output_version="v1",
            input_version="input-planner-v1",
            facts=(),
            inferences=(),
            recommendations=(),
            unknowns=(),
            invalidation_conditions=(),
            role_payload={
                "workflow_selection": "company_research",
                "node_ids": "node-1,node-2",
                "dependencies": "node-2<-node-1",
                "budget": "180s",
                "block_reasons": "none",
            },
        )

        CONTRACT_REGISTRY.validate_input(planner, planner_input)
        CONTRACT_REGISTRY.validate_output(
            planner,
            planner_output,
            planner_input,
        )

    def test_registry_rejects_contract_binding_and_required_field_failures(
        self,
    ) -> None:
        entry = self.catalog.get("tradingagents:fundamentals_analyst")
        valid_input = _valid_input(entry)
        valid_output = _valid_output(entry)

        with self.assertRaisesRegex(ValueError, "contract_id"):
            CONTRACT_REGISTRY.validate_input(
                entry,
                AgentInputEnvelope(
                    agent_id=entry.agent_id,
                    contract_id=self.catalog.get(
                        "tradingagents:market_analyst"
                    ).input_contract_id,
                    schema_version="1",
                    run_id="run",
                    workflow_id="company_research",
                    workflow_version="v1",
                    input_version="input-v1",
                    evidence=valid_input.evidence,
                    role_payload={"subject": "公司"},
                ),
            )
        with self.assertRaisesRegex(ValueError, "agent_id"):
            CONTRACT_REGISTRY.validate_output(
                entry,
                AgentOutputEnvelope(
                    agent_id="tradingagents:market_analyst",
                    contract_id=entry.output_contract_id,
                    schema_version="1",
                    run_id="run-1",
                    artifact_id="artifact",
                    output_version="v1",
                    input_version="input-v1",
                    facts=valid_output.facts,
                    inferences=(),
                    recommendations=valid_output.recommendations,
                    unknowns=valid_output.unknowns,
                    invalidation_conditions=valid_output.invalidation_conditions,
                    role_payload={"analysis": "错配"},
                ),
                valid_input,
            )
        with self.assertRaisesRegex(ValueError, "role_inputs"):
            CONTRACT_REGISTRY.validate_input(
                entry,
                AgentInputEnvelope(
                    agent_id=entry.agent_id,
                    contract_id=entry.input_contract_id,
                    schema_version="1",
                    run_id="run",
                    workflow_id="company_research",
                    workflow_version="v1",
                    input_version="input-v1",
                    evidence=valid_input.evidence,
                    role_payload={},
                ),
            )
        with self.assertRaisesRegex(ValueError, "schema_version"):
            CONTRACT_REGISTRY.validate_input(
                entry,
                AgentInputEnvelope(
                    agent_id=entry.agent_id,
                    contract_id=entry.input_contract_id,
                    schema_version="2",
                    run_id="run",
                    workflow_id="company_research",
                    workflow_version="v1",
                    input_version="input-v1",
                    evidence=valid_input.evidence,
                    role_payload={"subject": "公司"},
                ),
            )
        with self.assertRaisesRegex(ValueError, "subject"):
            CONTRACT_REGISTRY.validate_input(
                entry,
                AgentInputEnvelope(
                    agent_id=entry.agent_id,
                    contract_id=entry.input_contract_id,
                    schema_version="1",
                    run_id="run",
                    workflow_id="company_research",
                    workflow_version="v1",
                    input_version="input-v1",
                    evidence=valid_input.evidence,
                    role_payload={"not_subject": "公司"},
                ),
            )
        with self.assertRaisesRegex(ValueError, "approved evidence"):
            CONTRACT_REGISTRY.validate_input(
                entry,
                AgentInputEnvelope(
                    agent_id=entry.agent_id,
                    contract_id=entry.input_contract_id,
                    schema_version="1",
                    run_id="run",
                    workflow_id="company_research",
                    workflow_version="v1",
                    input_version="input-v1",
                    evidence=(),
                    role_payload={"subject": "公司"},
                ),
            )
        with self.assertRaisesRegex(ValueError, "cannot be empty"):
            CONTRACT_REGISTRY.validate_output(
                entry,
                AgentOutputEnvelope(
                    agent_id=entry.agent_id,
                    contract_id=entry.output_contract_id,
                    schema_version="1",
                    run_id="run-1",
                    artifact_id="artifact",
                    output_version="v1",
                    input_version="input-v1",
                    facts=(),
                    inferences=(),
                    recommendations=(),
                    unknowns=(),
                    invalidation_conditions=(),
                    role_payload={},
                ),
                valid_input,
            )
        with self.assertRaisesRegex(ValueError, "role_output"):
            CONTRACT_REGISTRY.validate_output(
                entry,
                AgentOutputEnvelope(
                    agent_id=entry.agent_id,
                    contract_id=entry.output_contract_id,
                    schema_version="1",
                    run_id="run-1",
                    artifact_id="artifact",
                    output_version="v1",
                    input_version="input-v1",
                    facts=valid_output.facts,
                    inferences=(),
                    recommendations=valid_output.recommendations,
                    unknowns=valid_output.unknowns,
                    invalidation_conditions=valid_output.invalidation_conditions,
                    role_payload={},
                ),
                valid_input,
            )
        with self.assertRaisesRegex(ValueError, "unknowns"):
            CONTRACT_REGISTRY.validate_output(
                entry,
                AgentOutputEnvelope(
                    agent_id=entry.agent_id,
                    contract_id=entry.output_contract_id,
                    schema_version="1",
                    run_id="run-1",
                    artifact_id="artifact",
                    output_version="v1",
                    input_version="input-v1",
                    facts=valid_output.facts,
                    inferences=(),
                    recommendations=valid_output.recommendations,
                    unknowns=(),
                    invalidation_conditions=valid_output.invalidation_conditions,
                    role_payload={"analysis": "结果"},
                ),
                valid_input,
            )
        with self.assertRaisesRegex(ValueError, "analysis"):
            CONTRACT_REGISTRY.validate_output(
                entry,
                replace(valid_output, role_payload={"not_analysis": "结果"}),
                valid_input,
            )
        with self.assertRaisesRegex(ValueError, "run_id"):
            CONTRACT_REGISTRY.validate_output(
                entry,
                replace(valid_output, run_id="other-run"),
                valid_input,
            )

    def test_text_and_reference_values_are_trimmed_and_deduplicated(self) -> None:
        evidence = EvidenceReference(" E1 ", " pandadata ", " v1 ", True)
        statement = EvidenceBoundStatement(" 收入增长。 ", (" E1 ",))

        self.assertEqual(evidence.evidence_id, "E1")
        self.assertEqual(statement.text, "收入增长。")
        self.assertEqual(statement.evidence_ids, ("E1",))
        with self.assertRaisesRegex(ValueError, "blank"):
            EvidenceReference(" ", "pandadata", "v1", True)
        with self.assertRaisesRegex(ValueError, "duplicates"):
            EvidenceBoundStatement("事实", ("E1", " E1 "))
        with self.assertRaisesRegex(ValueError, "conflict after trimming"):
            AgentInputEnvelope(
                agent_id="tradingagents:fundamentals_analyst",
                contract_id="financegod.agent-input.example.v1",
                schema_version="1",
                run_id="run",
                workflow_id="company_research",
                workflow_version="v1",
                input_version="input-v1",
                evidence=(evidence,),
                role_payload={" subject": "公司", "subject ": "另一公司"},
            )
        entry = self.catalog.get("tradingagents:fundamentals_analyst")
        with self.assertRaisesRegex(ValueError, "duplicates"):
            AgentOutputEnvelope(
                agent_id=entry.agent_id,
                contract_id=entry.output_contract_id,
                schema_version="1",
                run_id="run-1",
                artifact_id="artifact",
                output_version="v1",
                input_version="input-v1",
                facts=(statement,),
                inferences=(),
                recommendations=(),
                unknowns=("未知", " 未知 "),
                invalidation_conditions=("条件",),
                role_payload={"analysis": "结果"},
            )
        for field_name in ("unknowns", "invalidation_conditions"):
            arguments: dict[str, Any] = {
                "agent_id": entry.agent_id,
                "contract_id": entry.output_contract_id,
                "schema_version": "1",
                "run_id": "run-1",
                "artifact_id": "artifact",
                "output_version": "v1",
                "input_version": "input-v1",
                "facts": (statement,),
                "inferences": (),
                "recommendations": (),
                "unknowns": ("未知",),
                "invalidation_conditions": ("条件",),
                "role_payload": {"analysis": "结果"},
            }
            arguments[field_name] = (" ",)
            with self.subTest(field_name=field_name):
                with self.assertRaisesRegex(ValueError, "blank"):
                    AgentOutputEnvelope(**arguments)
        with self.assertRaisesRegex(ValueError, "duplicates"):
            AgentOutputEnvelope(
                agent_id=entry.agent_id,
                contract_id=entry.output_contract_id,
                schema_version="1",
                run_id="run-1",
                artifact_id="artifact",
                output_version="v1",
                input_version="input-v1",
                facts=(statement,),
                inferences=(),
                recommendations=(statement,),
                unknowns=("未知",),
                invalidation_conditions=("条件",),
                role_payload={"analysis": "结果"},
            )

    def test_requirement_resolver_uses_both_required_and_non_blocking(self) -> None:
        trader = self.catalog.get("tradingagents:trader")

        self.assertEqual(
            trader.requirement_for(WorkflowKey.ORDER_REVIEW),
            NodeRequirement.REQUIRED,
        )
        self.assertEqual(
            trader.requirement_for(
                WorkflowKey.ORDER_REVIEW,
                RequirementContext(order_review_mode=OrderReviewMode.MANUAL),
            ),
            NodeRequirement.NON_BLOCKING,
        )
        self.assertEqual(
            trader.requirement_for(
                WorkflowKey.SIMULATION_EXECUTION,
                RequirementContext(order_accepted=True),
            ),
            NodeRequirement.NON_BLOCKING,
        )
        self.assertEqual(
            trader.requirement_for(
                WorkflowKey.ORDER_REVIEW,
                RequirementContext(
                    order_review_mode=OrderReviewMode.MANUAL,
                    deterministic_critical_node=True,
                ),
            ),
            NodeRequirement.REQUIRED,
        )

    def test_timeouts_and_retry_policy_match_se_defaults(self) -> None:
        expected = {
            ExecutionType.PROMPT: 60,
            ExecutionType.DETERMINISTIC: 15,
            ExecutionType.SANDBOX: 120,
            ExecutionType.PLANNER: 15,
        }
        for entry in self.catalog.list():
            self.assertEqual(entry.timeout_seconds, expected[entry.execution_type])
            limits = entry.failure_policy.retry_limits
            self.assertEqual(limits[FailureKind.TRANSIENT], 2)
            self.assertEqual(limits[FailureKind.VALIDATION], 0)
            self.assertEqual(limits[FailureKind.AUTHENTICATION], 0)
            self.assertEqual(limits[FailureKind.PERMISSION], 0)
            self.assertEqual(
                entry.failure_policy.total_duration_seconds,
                entry.timeout_seconds * 3,
            )


if __name__ == "__main__":
    unittest.main()
