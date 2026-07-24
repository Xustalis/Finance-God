"""Versioned registry for the fifteen product workflows."""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from finance_god.agents.catalog import AgentGovernanceCatalog, PLANNER_ID
from finance_god.agents.contracts import (
    FailureKind,
    NodeRequirement,
    WorkflowCallMode,
    WorkflowKey,
)

WORKFLOW_REGISTRY_VERSION: Final = "finance-god-workflows-v1"
MAX_NODE_TIMEOUT_SECONDS: Final = 300
MAX_WORKFLOW_DURATION_SECONDS: Final = 3_600
MAX_WORKFLOW_ATTEMPTS: Final = 192


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class WorkflowNodeKind(StrEnum):
    AGENT = "agent"
    DETERMINISTIC_SERVICE = "deterministic_service"


class DeterministicResultContract(StrEnum):
    GENERIC = "generic"
    INPUT_QUALITY = "input_quality"
    ORDER_RISK_CHECK = "order_risk_check"
    SIMULATION_ORDER_ACCEPTANCE = "simulation_order_acceptance"
    SIMULATION_MARKET_VALIDATION = "simulation_market_validation"
    SIMULATION_MATCH = "simulation_match"
    SIMULATION_LEDGER_UPDATE = "simulation_ledger_update"


class InputQualityGate(StrEnum):
    REQUIRE_USABLE = "require_usable"
    ALLOW_DEGRADED_READ_ONLY = "allow_degraded_read_only"
    DIAGNOSTIC = "diagnostic"
    REQUIRE_EXECUTION_READY = "require_execution_ready"


class RetryBudget(FrozenModel):
    retry_limits: dict[FailureKind, int]
    total_attempt_limit: int = Field(ge=1, le=8)
    total_duration_seconds: int = Field(ge=1, le=900)

    @model_validator(mode="after")
    def validate_complete_policy(self) -> Self:
        if set(self.retry_limits) != set(FailureKind):
            raise ValueError("retry budget must define every FailureKind")
        if any(value < 0 for value in self.retry_limits.values()):
            raise ValueError("retry limits cannot be negative")
        if self.total_attempt_limit > 1 + sum(self.retry_limits.values()):
            raise ValueError("total attempt limit exceeds governed retry limits")
        return self


class WorkflowNodeDefinition(FrozenModel):
    node_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=80)
    title: str = Field(min_length=1, max_length=160)
    kind: WorkflowNodeKind
    agent_ids: tuple[str, ...] = ()
    service_id: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_.]*$",
        max_length=120,
    )
    dependencies: tuple[str, ...] = ()
    requirement: NodeRequirement
    timeout_seconds: int = Field(ge=1, le=MAX_NODE_TIMEOUT_SECONDS)
    retry_budget: RetryBudget
    tool_allowlist: frozenset[str] = frozenset()
    data_permissions: frozenset[str] = frozenset()
    resource_allowlist: frozenset[str] = frozenset()
    external_action_allowlist: frozenset[str] = frozenset()
    is_quality_gate: bool = False
    is_finalizer: bool = False
    writes_trade_facts: bool = False
    result_contract: DeterministicResultContract = (
        DeterministicResultContract.GENERIC
    )

    @model_validator(mode="after")
    def validate_kind_contract(self) -> Self:
        is_agent = self.kind is WorkflowNodeKind.AGENT
        if is_agent != bool(self.agent_ids):
            raise ValueError("Agent nodes require agent_ids and service nodes forbid them")
        if is_agent == (self.service_id is not None):
            raise ValueError("exactly one of agent_ids or service_id is required")
        if len(self.agent_ids) != len(set(self.agent_ids)):
            raise ValueError("Agent node cannot duplicate agent IDs")
        if len(self.dependencies) != len(set(self.dependencies)):
            raise ValueError("node dependencies cannot contain duplicates")
        if is_agent and (self.external_action_allowlist or self.writes_trade_facts):
            raise ValueError("Agent nodes cannot execute external or trade-write actions")
        if is_agent and self.result_contract is not DeterministicResultContract.GENERIC:
            raise ValueError("Agent nodes cannot declare deterministic result contracts")
        if self.writes_trade_facts and not self.service_id:
            raise ValueError("trade facts require a deterministic service")
        return self


class WorkflowDefinition(FrozenModel):
    prd_id: str = Field(pattern=r"^WF-[A-Z]{2}-01$")
    workflow_key: WorkflowKey
    version: str = WORKFLOW_REGISTRY_VERSION
    title: str = Field(min_length=1, max_length=160)
    final_artifact_type: str = Field(pattern=r"^[A-Z][A-Za-z0-9]*$")
    input_quality_gate: InputQualityGate
    core_stages: tuple[str, ...] = Field(min_length=1)
    nodes: tuple[WorkflowNodeDefinition, ...] = Field(min_length=1, max_length=64)
    maximum_duration_seconds: int = Field(
        ge=1,
        le=MAX_WORKFLOW_DURATION_SECONDS,
    )
    maximum_total_attempts: int = Field(ge=1, le=MAX_WORKFLOW_ATTEMPTS)
    allows_trade_eligibility: bool = True

    @model_validator(mode="after")
    def validate_graph(self) -> Self:
        node_ids = {node.node_id for node in self.nodes}
        if len(node_ids) != len(self.nodes):
            raise ValueError("workflow node IDs must be unique")
        for node in self.nodes:
            missing = set(node.dependencies) - node_ids
            if missing:
                raise ValueError(
                    f"{node.node_id} has unknown dependencies: {sorted(missing)}"
                )
            if node.node_id in node.dependencies:
                raise ValueError("workflow node cannot depend on itself")
        _require_acyclic(self.nodes)
        if sum(node.retry_budget.total_attempt_limit for node in self.nodes) > (
            self.maximum_total_attempts
        ):
            raise ValueError("node attempt budgets exceed workflow attempt limit")
        finalizers = [node for node in self.nodes if node.is_finalizer]
        if len(finalizers) != 1:
            raise ValueError("workflow requires exactly one finalizer")
        if not any(node.is_quality_gate for node in self.nodes):
            raise ValueError("workflow requires a deterministic quality gate")
        return self


class DeterministicServicePolicy(FrozenModel):
    service_id: str
    tool_allowlist: frozenset[str]
    resource_allowlist: frozenset[str] = frozenset()
    external_action_allowlist: frozenset[str] = frozenset()
    may_write_trade_facts: bool = False


def _service_policy(
    service_id: str,
    *,
    writes: bool = False,
) -> DeterministicServicePolicy:
    tools = {"deterministic.compute"}
    actions: set[str] = set()
    if writes:
        tools.add("simulation.fact.write")
        actions.add("simulation_fact_commit")
    return DeterministicServicePolicy(
        service_id=service_id,
        tool_allowlist=frozenset(tools),
        external_action_allowlist=frozenset(actions),
        may_write_trade_facts=writes,
    )


DETERMINISTIC_SERVICE_POLICIES: Final[
    Mapping[str, DeterministicServicePolicy]
] = MappingProxyType(
    {
        policy.service_id: policy
        for policy in (
            _service_policy("workflow.input_quality_gate"),
            _service_policy("workflow.artifact_finalize"),
            _service_policy("portfolio.stress_calculate"),
            _service_policy("portfolio.optimize"),
            _service_policy("trade_plan.calculate"),
            _service_policy("order_review.calculate"),
            _service_policy("risk.pre_submit"),
            _service_policy("data_quality.diagnose"),
            _service_policy("fund.rules_calculate"),
            _service_policy("cross_market.align"),
            _service_policy("strategy.monitor_compare"),
            _service_policy("simulation.order_accept", writes=True),
            _service_policy("simulation.market_validate"),
            _service_policy("simulation.match", writes=True),
            _service_policy("simulation.ledger_update", writes=True),
            _service_policy("simulation.execution_monitor"),
        )
    }
)


_PRD_WORKFLOWS: Final = (
    (
        "WF-CR-01",
        WorkflowKey.COMPANY_RESEARCH,
        "公司研究",
        "ResearchMemo",
        InputQualityGate.ALLOW_DEGRADED_READ_ONLY,
        ("事实审阅", "正反观点与风险辩论", "研究治理汇总"),
        (),
    ),
    (
        "WF-MC-01",
        WorkflowKey.MARKET_CONTEXT,
        "市场环境",
        "MarketContext",
        InputQualityGate.REQUIRE_USABLE,
        ("市场监控", "新闻与情绪解释", "治理复核"),
        (),
    ),
    (
        "WF-PS-01",
        WorkflowKey.PORTFOLIO_STRESS,
        "组合压力",
        "PortfolioRiskReview",
        InputQualityGate.REQUIRE_USABLE,
        ("相关性监控", "拥挤风险监控", "风险辩论与治理"),
        ("portfolio.stress_calculate",),
    ),
    (
        "WF-SV-01",
        WorkflowKey.STRATEGY_VALIDATION,
        "策略验证",
        "StrategyValidationDossier",
        InputQualityGate.REQUIRE_USABLE,
        ("需求", "Alpha设计", "回测", "验收测试", "治理汇总"),
        (),
    ),
    (
        "WF-RO-01",
        WorkflowKey.REVIEW_ONLY,
        "只读复核",
        "ReviewOnlyMemo",
        InputQualityGate.ALLOW_DEGRADED_READ_ONLY,
        ("证据与下行风险只读复核",),
        (),
    ),
    (
        "WF-DQ-01",
        WorkflowKey.DATA_QUALITY_REVIEW,
        "数据质量诊断",
        "DataQualityReport",
        InputQualityGate.DIAGNOSTIC,
        ("数据缺口与可用性诊断",),
        ("data_quality.diagnose",),
    ),
    (
        "WF-FR-01",
        WorkflowKey.FUND_RESEARCH,
        "基金研究",
        "FundResearchReport",
        InputQualityGate.REQUIRE_USABLE,
        ("身份与规则", "持仓穿透与风格", "费用与同类比较", "治理"),
        ("fund.rules_calculate",),
    ),
    (
        "WF-PC-01",
        WorkflowKey.PORTFOLIO_CONSTRUCTION,
        "组合构建",
        "PortfolioProposal",
        InputQualityGate.REQUIRE_USABLE,
        ("输入校验", "候选权重", "确定性优化", "压力复核", "治理"),
        ("portfolio.optimize", "portfolio.stress_calculate"),
    ),
    (
        "WF-TP-01",
        WorkflowKey.TRADE_PLAN_GENERATION,
        "交易计划生成",
        "TradePlan",
        InputQualityGate.REQUIRE_EXECUTION_READY,
        ("计划目标", "动作草案", "费用现金偏离计算", "用户解释"),
        ("trade_plan.calculate",),
    ),
    (
        "WF-OR-01",
        WorkflowKey.ORDER_REVIEW,
        "订单复核",
        "OrderReviewMemo",
        InputQualityGate.REQUIRE_EXECUTION_READY,
        ("草稿解析", "组合费用偏离计算", "Agent解释", "正式风控", "最终复核"),
        ("order_review.calculate", "risk.pre_submit"),
    ),
    (
        "WF-SE-01",
        WorkflowKey.SIMULATION_EXECUTION,
        "仿真执行",
        "ExecutionRun",
        InputQualityGate.REQUIRE_EXECUTION_READY,
        ("订单受理", "市场校验", "撮合", "账本更新", "监控解释"),
        (
            "simulation.order_accept",
            "simulation.market_validate",
            "simulation.match",
            "simulation.ledger_update",
            "simulation.execution_monitor",
        ),
    ),
    (
        "WF-PR-01",
        WorkflowKey.POST_TRADE_REVIEW,
        "交易后复盘",
        "TradeReview",
        InputQualityGate.REQUIRE_USABLE,
        ("计划成交对齐", "执行质量", "组合影响", "假设复核", "下一步"),
        (),
    ),
    (
        "WF-EI-01",
        WorkflowKey.EVENT_IMPACT,
        "事件影响",
        "EventImpactReport",
        InputQualityGate.REQUIRE_USABLE,
        ("事件事实", "影响路径", "正反情景", "组合影响", "治理"),
        (),
    ),
    (
        "WF-CM-01",
        WorkflowKey.CROSS_MARKET_ANALYSIS,
        "跨市场分析",
        "CrossMarketReport",
        InputQualityGate.REQUIRE_USABLE,
        ("市场数据对齐", "相关性与汇率", "新闻宏观解释", "组合影响", "治理"),
        ("cross_market.align",),
    ),
    (
        "WF-SM-01",
        WorkflowKey.STRATEGY_MONITORING,
        "策略监控",
        "StrategyMonitorReport",
        InputQualityGate.REQUIRE_USABLE,
        ("输入版本比较", "指标漂移", "失效条件", "风险与治理"),
        ("strategy.monitor_compare",),
    ),
)


def _retry_budget(
    *,
    attempts: int = 3,
    duration: int = 180,
) -> RetryBudget:
    return RetryBudget(
        retry_limits={
            FailureKind.TRANSIENT: attempts - 1,
            FailureKind.VALIDATION: 0,
            FailureKind.AUTHENTICATION: 0,
            FailureKind.PERMISSION: 0,
        },
        total_attempt_limit=attempts,
        total_duration_seconds=duration,
    )


class FormalWorkflowRegistry:
    """Immutable workflow registry validated against Agent governance."""

    def __init__(
        self,
        catalog: AgentGovernanceCatalog,
        definitions: Iterable[WorkflowDefinition],
    ) -> None:
        self._catalog = catalog
        rows = tuple(definitions)
        by_key = {row.workflow_key: row for row in rows}
        if set(by_key) != set(WorkflowKey) or len(rows) != len(WorkflowKey):
            raise ValueError("formal workflow registry must contain exactly 15 keys")
        prd_ids = [row.prd_id for row in rows]
        if len(prd_ids) != len(set(prd_ids)):
            raise ValueError("formal workflow PRD IDs must be unique")
        for definition in rows:
            self._validate_governance(definition)
        self._definitions = MappingProxyType(by_key)

    @classmethod
    def build_default(
        cls,
        catalog: AgentGovernanceCatalog | None = None,
    ) -> FormalWorkflowRegistry:
        governed_catalog = catalog or AgentGovernanceCatalog()
        definitions = tuple(
            _definition_from_prd(governed_catalog, *row) for row in _PRD_WORKFLOWS
        )
        return cls(governed_catalog, definitions)

    @property
    def version(self) -> str:
        return WORKFLOW_REGISTRY_VERSION

    def get(self, key: WorkflowKey | str) -> WorkflowDefinition:
        try:
            normalized = key if isinstance(key, WorkflowKey) else WorkflowKey(key)
        except ValueError as error:
            raise ValueError(f"unknown formal workflow: {key}") from error
        return self._definitions[normalized]

    def list(self) -> tuple[WorkflowDefinition, ...]:
        return tuple(self._definitions[key] for key in WorkflowKey)

    def as_mapping(self) -> Mapping[WorkflowKey, WorkflowDefinition]:
        return self._definitions

    def _validate_governance(self, definition: WorkflowDefinition) -> None:
        actual_agents = {
            agent_id for node in definition.nodes for agent_id in node.agent_ids
        }
        mandatory_agents = {
            entry.agent_id
            for entry in self._catalog.list()
            if entry.declared_call_mode(definition.workflow_key)
            is WorkflowCallMode.MANDATORY
        }
        if actual_agents != mandatory_agents:
            raise ValueError(
                f"{definition.workflow_key.value} Agent set differs from governance; "
                f"missing={sorted(mandatory_agents - actual_agents)}, "
                f"unexpected={sorted(actual_agents - mandatory_agents)}"
            )
        for node in definition.nodes:
            if node.kind is WorkflowNodeKind.AGENT:
                for agent_id in node.agent_ids:
                    entry = self._catalog.get(agent_id)
                    if (
                        entry.declared_call_mode(definition.workflow_key)
                        is WorkflowCallMode.DENIED
                    ):
                        raise ValueError(
                            f"{agent_id} is denied for {definition.workflow_key.value}"
                        )
                    if not node.tool_allowlist.issubset(entry.tool_allowlist):
                        raise ValueError(f"{agent_id} tool allowlist exceeded")
                    if not node.data_permissions.issubset(
                        entry.data_permission_allowlist
                    ):
                        raise ValueError(f"{agent_id} data permissions exceeded")
            else:
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
                    raise ValueError("service is not permitted to write trade facts")
                if (
                    node.writes_trade_facts
                    and definition.workflow_key
                    is not WorkflowKey.SIMULATION_EXECUTION
                ):
                    raise ValueError(
                        "only simulation_execution may write simulated trade facts"
                    )


def _definition_from_prd(
    catalog: AgentGovernanceCatalog,
    prd_id: str,
    workflow_key: WorkflowKey,
    title: str,
    final_artifact_type: str,
    input_quality_gate: InputQualityGate,
    core_stages: tuple[str, ...],
    service_ids: tuple[str, ...],
) -> WorkflowDefinition:
    mandatory = tuple(
        entry
        for entry in catalog.list()
        if entry.declared_call_mode(workflow_key) is WorkflowCallMode.MANDATORY
    )
    planner = catalog.get(PLANNER_ID)
    governed_agents = tuple(entry for entry in mandatory if entry.agent_id != PLANNER_ID)
    nodes: list[WorkflowNodeDefinition] = [
        WorkflowNodeDefinition(
            node_id="planner",
            title="Planner 固定路由与预算",
            kind=WorkflowNodeKind.AGENT,
            agent_ids=(PLANNER_ID,),
            requirement=NodeRequirement.REQUIRED,
            timeout_seconds=planner.timeout_seconds,
            retry_budget=_retry_budget(
                attempts=planner.failure_policy.total_attempt_limit,
                duration=planner.failure_policy.total_duration_seconds,
            ),
            tool_allowlist=planner.tool_allowlist,
            data_permissions=planner.data_permission_allowlist,
        ),
        _service_node(
            node_id="input_quality_gate",
            title="确定性输入质量门",
            service_id="workflow.input_quality_gate",
            dependencies=("planner",),
            is_quality_gate=True,
        ),
    ]
    previous = "input_quality_gate"
    if governed_agents:
        tools = set(governed_agents[0].tool_allowlist)
        permissions = set(governed_agents[0].data_permission_allowlist)
        for entry in governed_agents[1:]:
            tools.intersection_update(entry.tool_allowlist)
            permissions.intersection_update(entry.data_permission_allowlist)
        agent_timeout = max(entry.timeout_seconds for entry in governed_agents)
        nodes.append(
            WorkflowNodeDefinition(
                node_id="governed_agents",
                title="治理目录要求的 Agent 协作",
                kind=WorkflowNodeKind.AGENT,
                agent_ids=tuple(entry.agent_id for entry in governed_agents),
                dependencies=(previous,),
                requirement=NodeRequirement.REQUIRED,
                timeout_seconds=min(agent_timeout, MAX_NODE_TIMEOUT_SECONDS),
                retry_budget=_retry_budget(),
                tool_allowlist=frozenset(tools),
                data_permissions=frozenset(permissions),
            )
        )
        previous = "governed_agents"
    for index, service_id in enumerate(service_ids, start=1):
        is_monitor = service_id == "simulation.execution_monitor"
        node_id = f"service_{index}"
        nodes.append(
            _service_node(
                node_id=node_id,
                title=service_id,
                service_id=service_id,
                dependencies=(previous,),
                requirement=(
                    NodeRequirement.NON_BLOCKING
                    if is_monitor
                    else NodeRequirement.REQUIRED
                ),
                is_quality_gate=service_id == "risk.pre_submit",
            )
        )
        previous = node_id
    nodes.append(
        _service_node(
            node_id="artifact_finalize",
            title="版本化最终产物",
            service_id="workflow.artifact_finalize",
            dependencies=(previous,),
            is_finalizer=True,
        )
    )
    return WorkflowDefinition(
        prd_id=prd_id,
        workflow_key=workflow_key,
        title=title,
        final_artifact_type=final_artifact_type,
        input_quality_gate=input_quality_gate,
        core_stages=core_stages,
        nodes=tuple(nodes),
        maximum_duration_seconds=min(
            MAX_WORKFLOW_DURATION_SECONDS,
            max(300, sum(node.timeout_seconds for node in nodes)),
        ),
        maximum_total_attempts=sum(
            node.retry_budget.total_attempt_limit for node in nodes
        ),
        allows_trade_eligibility=workflow_key
        not in {WorkflowKey.REVIEW_ONLY, WorkflowKey.DATA_QUALITY_REVIEW},
    )


def _service_node(
    *,
    node_id: str,
    title: str,
    service_id: str,
    dependencies: tuple[str, ...],
    requirement: NodeRequirement = NodeRequirement.REQUIRED,
    is_quality_gate: bool = False,
    is_finalizer: bool = False,
) -> WorkflowNodeDefinition:
    policy = DETERMINISTIC_SERVICE_POLICIES[service_id]
    result_contract = {
        "workflow.input_quality_gate": DeterministicResultContract.INPUT_QUALITY,
        "risk.pre_submit": DeterministicResultContract.ORDER_RISK_CHECK,
        "simulation.order_accept": (
            DeterministicResultContract.SIMULATION_ORDER_ACCEPTANCE
        ),
        "simulation.market_validate": (
            DeterministicResultContract.SIMULATION_MARKET_VALIDATION
        ),
        "simulation.match": DeterministicResultContract.SIMULATION_MATCH,
        "simulation.ledger_update": (
            DeterministicResultContract.SIMULATION_LEDGER_UPDATE
        ),
    }.get(service_id, DeterministicResultContract.GENERIC)
    return WorkflowNodeDefinition(
        node_id=node_id,
        title=title,
        kind=WorkflowNodeKind.DETERMINISTIC_SERVICE,
        service_id=service_id,
        dependencies=dependencies,
        requirement=requirement,
        timeout_seconds=60,
        retry_budget=_retry_budget(),
        tool_allowlist=policy.tool_allowlist,
        resource_allowlist=policy.resource_allowlist,
        external_action_allowlist=policy.external_action_allowlist,
        writes_trade_facts=policy.may_write_trade_facts,
        result_contract=result_contract,
        is_quality_gate=is_quality_gate,
        is_finalizer=is_finalizer,
    )


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
            raise ValueError("workflow DAG contains a cycle")
        remaining -= ready
