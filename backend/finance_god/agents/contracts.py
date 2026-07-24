"""Immutable product governance contracts for the 44-Agent capability catalog."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class WorkflowKey(str, Enum):
    COMPANY_RESEARCH = "company_research"
    MARKET_CONTEXT = "market_context"
    PORTFOLIO_STRESS = "portfolio_stress"
    STRATEGY_VALIDATION = "strategy_validation"
    REVIEW_ONLY = "review_only"
    DATA_QUALITY_REVIEW = "data_quality_review"
    FUND_RESEARCH = "fund_research"
    PORTFOLIO_CONSTRUCTION = "portfolio_construction"
    TRADE_PLAN_GENERATION = "trade_plan_generation"
    ORDER_REVIEW = "order_review"
    SIMULATION_EXECUTION = "simulation_execution"
    POST_TRADE_REVIEW = "post_trade_review"
    EVENT_IMPACT = "event_impact"
    CROSS_MARKET_ANALYSIS = "cross_market_analysis"
    STRATEGY_MONITORING = "strategy_monitoring"


class WorkflowCallMode(str, Enum):
    MANDATORY = "M"
    CONDITIONAL = "C"
    DENIED = "denied"


class ImpactClass(str, Enum):
    READ_ONLY = "read_only"
    COMPUTE = "compute"
    SANDBOX_CODE = "sandbox_code"
    EXECUTION_FORBIDDEN = "execution_forbidden"


class RiskLevel(str, Enum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


class ExecutionType(str, Enum):
    PROMPT = "prompt"
    DETERMINISTIC = "deterministic"
    SANDBOX = "sandbox"
    PLANNER = "planner"


class NodeRequirement(str, Enum):
    REQUIRED = "required"
    NON_BLOCKING = "non_blocking"


class OrderReviewMode(str, Enum):
    PLANNED = "planned"
    MANUAL = "manual"


class FailureKind(str, Enum):
    TRANSIENT = "transient"
    VALIDATION = "validation"
    AUTHENTICATION = "authentication"
    PERMISSION = "permission"


class SelectionSignal(str, Enum):
    ISSUER_OR_UNDERLYING = "issuer_or_underlying"
    QUALIFIED_SENTIMENT_EVIDENCE = "qualified_sentiment_evidence"
    REQUIRES_DEBATE = "requires_debate"
    REQUIRES_CODE_IMPLEMENTATION = "requires_code_implementation"
    REQUIRES_NON_ALPHA_IMPLEMENTATION = "requires_non_alpha_implementation"
    TECHNICAL_FAULT = "technical_fault"
    AI_MODEL_OR_QUALITY_ISSUE = "ai_model_or_quality_issue"
    REQUIRES_REPORT_REVIEW = "requires_report_review"
    REQUIRES_UI_TAGLINE = "requires_ui_tagline"
    COMPLEX_PANDA_TRADING_DEVELOPMENT = "complex_panda_trading_development"


@dataclass(frozen=True, slots=True)
class WorkflowSelectionContext:
    selected_agent_ids: frozenset[str] = frozenset()
    signals: frozenset[SelectionSignal] = frozenset()
    asset_kinds: frozenset[str] = frozenset()
    available_resources: frozenset[str] = frozenset()
    data_capabilities: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class ConditionalRule:
    condition_id: str
    description: str
    required_signals: frozenset[SelectionSignal] = frozenset()
    required_asset_kinds: frozenset[str] = frozenset()
    required_resources: frozenset[str] = frozenset()
    required_data_capabilities: frozenset[str] = frozenset()

    def matches(
        self,
        agent_id: str,
        context: WorkflowSelectionContext | None,
    ) -> bool:
        if context is None or agent_id not in context.selected_agent_ids:
            return False
        if not self.required_signals.issubset(context.signals):
            return False
        if self.required_asset_kinds and self.required_asset_kinds.isdisjoint(
            context.asset_kinds
        ):
            return False
        if not self.required_resources.issubset(context.available_resources):
            return False
        return self.required_data_capabilities.issubset(context.data_capabilities)


@dataclass(frozen=True, slots=True)
class WorkflowDecision:
    mode: WorkflowCallMode
    conditional_rule: ConditionalRule | None = None

    def __post_init__(self) -> None:
        if (self.mode is WorkflowCallMode.CONDITIONAL) != (
            self.conditional_rule is not None
        ):
            raise ValueError("only conditional decisions may carry a condition rule")


@dataclass(frozen=True, slots=True)
class RequirementContext:
    order_review_mode: OrderReviewMode | None = None
    order_accepted: bool = False
    deterministic_critical_node: bool = False


@dataclass(frozen=True, slots=True)
class FailurePolicy:
    retry_limits: Mapping[FailureKind, int]
    total_attempt_limit: int
    total_duration_seconds: int
    terminal_behavior: str = "fail_explicitly"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "retry_limits", MappingProxyType(dict(self.retry_limits))
        )
        if frozenset(self.retry_limits) != frozenset(FailureKind):
            raise ValueError("retry policy must define every governed failure kind")
        if any(limit < 0 for limit in self.retry_limits.values()):
            raise ValueError("retry limits cannot be negative")
        if self.total_attempt_limit < 1 or self.total_duration_seconds < 1:
            raise ValueError("retry policy limits must be positive")


@dataclass(frozen=True, slots=True)
class VendorCapabilitySnapshot:
    agent_id: str
    fingerprint: str
    adapter: str
    minimum_profile: str
    required_resources: frozenset[str]
    declared_external_actions: frozenset[str]
    denied_external_actions: frozenset[str]
    declared_authorizations_by_task: tuple[tuple[str, frozenset[str]], ...]
    denied_authorizations_by_task: tuple[tuple[str, frozenset[str]], ...]
    effective_authorizations_by_task: tuple[tuple[str, frozenset[str]], ...]
    effective_external_actions: frozenset[str]
    source: str
    source_path: str
    upstream_path: str
    license: str


@dataclass(frozen=True, slots=True)
class ContractFieldDescriptor:
    name: str
    value_type: str
    required: bool
    description: str


@dataclass(frozen=True, slots=True)
class ContractDescriptor:
    contract_id: str
    version: str
    fields: tuple[ContractFieldDescriptor, ...]
    purpose: str
    required_non_empty_fields: frozenset[str] = frozenset()
    required_role_payload_keys: frozenset[str] = frozenset()


def _required_text(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be blank")
    return normalized


def _unique_texts(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    normalized = tuple(_required_text(item, field_name) for item in values)
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return normalized


def _role_payload(value: Mapping[str, str]) -> Mapping[str, str]:
    normalized: dict[str, str] = {}
    for key, item in value.items():
        normalized_key = _required_text(key, "role_payload key")
        if normalized_key in normalized:
            raise ValueError("role_payload keys conflict after trimming")
        normalized[normalized_key] = _required_text(item, "role_payload value")
    return MappingProxyType(normalized)


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    evidence_id: str
    source_id: str
    source_version: str
    approved: bool

    def __post_init__(self) -> None:
        for field_name in ("evidence_id", "source_id", "source_version"):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name),
            )


@dataclass(frozen=True, slots=True)
class AgentInputEnvelope:
    agent_id: str
    contract_id: str
    schema_version: str
    run_id: str
    workflow_id: str
    workflow_version: str
    input_version: str
    evidence: tuple[EvidenceReference, ...]
    role_payload: Mapping[str, str]

    def __post_init__(self) -> None:
        for field_name in (
            "agent_id",
            "contract_id",
            "schema_version",
            "run_id",
            "workflow_id",
            "workflow_version",
            "input_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name),
            )
        object.__setattr__(self, "role_payload", _role_payload(self.role_payload))
        identifiers = [item.evidence_id for item in self.evidence]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("evidence identifiers must be unique")
        rejected = sorted(
            item.evidence_id for item in self.evidence if not item.approved
        )
        if rejected:
            raise ValueError(f"Agent input contains unapproved evidence: {rejected}")


@dataclass(frozen=True, slots=True)
class EvidenceBoundStatement:
    text: str
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "text", _required_text(self.text, "statement text"))
        evidence_ids = _unique_texts(self.evidence_ids, "statement evidence_ids")
        object.__setattr__(self, "evidence_ids", evidence_ids)
        if not evidence_ids:
            raise ValueError("statements require evidence references")


@dataclass(frozen=True, slots=True)
class AgentOutputEnvelope:
    agent_id: str
    contract_id: str
    schema_version: str
    run_id: str
    artifact_id: str
    output_version: str
    input_version: str
    facts: tuple[EvidenceBoundStatement, ...]
    inferences: tuple[EvidenceBoundStatement, ...]
    recommendations: tuple[EvidenceBoundStatement, ...]
    unknowns: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    role_payload: Mapping[str, str]

    def __post_init__(self) -> None:
        for field_name in (
            "agent_id",
            "contract_id",
            "schema_version",
            "run_id",
            "artifact_id",
            "output_version",
            "input_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name),
            )
        object.__setattr__(self, "unknowns", _unique_texts(self.unknowns, "unknowns"))
        object.__setattr__(
            self,
            "invalidation_conditions",
            _unique_texts(
                self.invalidation_conditions,
                "invalidation_conditions",
            ),
        )
        object.__setattr__(self, "role_payload", _role_payload(self.role_payload))
        statements = (*self.facts, *self.inferences, *self.recommendations)
        statement_keys = [(item.text, item.evidence_ids) for item in statements]
        if len(statement_keys) != len(set(statement_keys)):
            raise ValueError("output statements cannot contain duplicates")

    def validate_against(self, input_envelope: AgentInputEnvelope) -> None:
        if self.agent_id != input_envelope.agent_id:
            raise ValueError("Agent output agent_id does not match its input")
        if self.run_id != input_envelope.run_id:
            raise ValueError("Agent output run_id does not match its input")
        if self.input_version != input_envelope.input_version:
            raise ValueError("Agent output input_version does not match its input")
        available = {item.evidence_id for item in input_envelope.evidence}
        referenced = {
            evidence_id
            for statement in (*self.facts, *self.inferences, *self.recommendations)
            for evidence_id in statement.evidence_ids
        }
        unknown = sorted(referenced - available)
        if unknown:
            raise ValueError(f"Agent output references unavailable evidence: {unknown}")


@dataclass(frozen=True, slots=True)
class AgentGovernanceEntry:
    agent_id: str
    chinese_responsibility: str
    capability_boundary: str
    workflow_matrix: Mapping[WorkflowKey, WorkflowDecision]
    input_contract_id: str
    output_contract_id: str
    tool_allowlist: frozenset[str]
    data_permission_allowlist: frozenset[str]
    risk_level: RiskLevel
    impact_class: ImpactClass
    execution_type: ExecutionType
    timeout_seconds: int
    failure_policy: FailurePolicy
    default_requirement: NodeRequirement
    evidence_requirements: frozenset[str]
    governance_relations: tuple[str, ...]
    prohibited_behaviors: tuple[str, ...]
    version: str
    vendor_capability: VendorCapabilitySnapshot | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "workflow_matrix",
            MappingProxyType(dict(self.workflow_matrix)),
        )
        if frozenset(self.workflow_matrix) != frozenset(WorkflowKey):
            raise ValueError(f"{self.agent_id} must declare all 15 workflow decisions")
        if self.timeout_seconds < 1:
            raise ValueError(f"{self.agent_id} timeout must be positive")

    def declared_call_mode(self, workflow: WorkflowKey | str) -> WorkflowCallMode:
        try:
            key = (
                workflow if isinstance(workflow, WorkflowKey) else WorkflowKey(workflow)
            )
        except ValueError:
            return WorkflowCallMode.DENIED
        return self.workflow_matrix[key].mode

    def resolve_call_mode(
        self,
        workflow: WorkflowKey | str,
        context: WorkflowSelectionContext | None = None,
    ) -> WorkflowCallMode:
        try:
            key = (
                workflow if isinstance(workflow, WorkflowKey) else WorkflowKey(workflow)
            )
        except ValueError:
            return WorkflowCallMode.DENIED
        decision = self.workflow_matrix[key]
        if decision.mode is not WorkflowCallMode.CONDITIONAL:
            return decision.mode
        rule = decision.conditional_rule
        if rule is None or not rule.matches(self.agent_id, context):
            return WorkflowCallMode.DENIED
        return WorkflowCallMode.CONDITIONAL

    def is_allowed(
        self,
        workflow: WorkflowKey | str,
        context: WorkflowSelectionContext | None = None,
    ) -> bool:
        return self.resolve_call_mode(workflow, context) is not WorkflowCallMode.DENIED

    def requirement_for(
        self,
        workflow: WorkflowKey | str,
        context: RequirementContext | None = None,
    ) -> NodeRequirement:
        if context is None or context.deterministic_critical_node:
            return self.default_requirement
        try:
            key = (
                workflow if isinstance(workflow, WorkflowKey) else WorkflowKey(workflow)
            )
        except ValueError:
            return self.default_requirement
        if (
            key is WorkflowKey.ORDER_REVIEW
            and context.order_review_mode is OrderReviewMode.MANUAL
        ):
            return NodeRequirement.NON_BLOCKING
        if key is WorkflowKey.SIMULATION_EXECUTION and context.order_accepted:
            return NodeRequirement.NON_BLOCKING
        return self.default_requirement

    def allows_tool(self, tool_id: str) -> bool:
        return tool_id in self.tool_allowlist

    def allows_data_permission(self, permission_id: str) -> bool:
        return permission_id in self.data_permission_allowlist

    def allows_external_action(self, action_id: str) -> bool:
        return False


class ContractRegistry(Mapping[str, ContractDescriptor]):
    """Immutable descriptors plus executable envelope validation."""

    def __init__(self, descriptors: Mapping[str, ContractDescriptor]) -> None:
        self._descriptors = MappingProxyType(dict(descriptors))

    def __getitem__(self, contract_id: str) -> ContractDescriptor:
        return self._descriptors[contract_id]

    def __iter__(self) -> Iterator[str]:
        return iter(self._descriptors)

    def __len__(self) -> int:
        return len(self._descriptors)

    def validate_input(
        self,
        entry: AgentGovernanceEntry,
        envelope: AgentInputEnvelope,
    ) -> None:
        descriptor = self._bound_descriptor(
            entry.agent_id,
            entry.input_contract_id,
            envelope.agent_id,
            envelope.contract_id,
            envelope.schema_version,
        )
        self._require_declared_fields(
            descriptor,
            {
                "agent_id": envelope.agent_id,
                "contract_id": envelope.contract_id,
                "schema_version": envelope.schema_version,
                "run_id": envelope.run_id,
                "workflow_id": envelope.workflow_id,
                "workflow_version": envelope.workflow_version,
                "input_version": envelope.input_version,
                "evidence": envelope.evidence,
                "role_inputs": envelope.role_payload,
            },
        )
        if entry.execution_type is ExecutionType.PROMPT and not envelope.evidence:
            raise ValueError("Prompt Agent input requires approved evidence")

    def validate_output(
        self,
        entry: AgentGovernanceEntry,
        envelope: AgentOutputEnvelope,
        input_envelope: AgentInputEnvelope,
    ) -> None:
        self.validate_input(entry, input_envelope)
        descriptor = self._bound_descriptor(
            entry.agent_id,
            entry.output_contract_id,
            envelope.agent_id,
            envelope.contract_id,
            envelope.schema_version,
        )
        self._require_declared_fields(
            descriptor,
            {
                "agent_id": envelope.agent_id,
                "contract_id": envelope.contract_id,
                "schema_version": envelope.schema_version,
                "artifact_id": envelope.artifact_id,
                "run_id": envelope.run_id,
                "output_version": envelope.output_version,
                "input_version": envelope.input_version,
                "facts": envelope.facts,
                "inferences": envelope.inferences,
                "recommendations": envelope.recommendations,
                "unknowns": envelope.unknowns,
                "invalidation_conditions": envelope.invalidation_conditions,
                "role_output": envelope.role_payload,
            },
        )
        if not any(
            (
                envelope.facts,
                envelope.inferences,
                envelope.recommendations,
                envelope.unknowns,
                envelope.invalidation_conditions,
                envelope.role_payload,
            )
        ):
            raise ValueError("Agent output cannot be empty")
        envelope.validate_against(input_envelope)

    def _bound_descriptor(
        self,
        expected_agent_id: str,
        expected_contract_id: str,
        actual_agent_id: str,
        actual_contract_id: str,
        schema_version: str,
    ) -> ContractDescriptor:
        if actual_agent_id != expected_agent_id:
            raise ValueError("envelope agent_id does not match catalog entry")
        if actual_contract_id != expected_contract_id:
            raise ValueError("envelope contract_id does not match catalog entry")
        descriptor = self[actual_contract_id]
        if schema_version != descriptor.version:
            raise ValueError("envelope schema_version does not match contract")
        return descriptor

    @staticmethod
    def _require_declared_fields(
        descriptor: ContractDescriptor,
        values: Mapping[str, object],
    ) -> None:
        required = {field.name for field in descriptor.fields if field.required}
        missing = sorted(required - set(values))
        if missing:
            raise ValueError(f"contract required fields are not bound: {missing}")
        empty = sorted(
            field_name
            for field_name in descriptor.required_non_empty_fields
            if not values.get(field_name)
        )
        if empty:
            raise ValueError(f"contract required fields cannot be empty: {empty}")
        role_payload = values.get("role_inputs") or values.get("role_output")
        if descriptor.required_role_payload_keys:
            if not isinstance(role_payload, Mapping):
                raise ValueError("contract role payload is not bound")
            missing_role_keys = sorted(
                descriptor.required_role_payload_keys - set(role_payload)
            )
            if missing_role_keys:
                raise ValueError(
                    f"contract role payload is missing keys: {missing_role_keys}"
                )
