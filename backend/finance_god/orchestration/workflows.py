"""Scenario-aware, staged workflows built on the unified Agent runtime."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field
from research_runtime import (
    AgentRequest,
    AgentRun,
    AssetKind,
    ExecutionProfile,
)
from research_runtime.models import EvidenceRecord

_WORKFLOW_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_MAX_WORKFLOW_ID_LENGTH = 72


class WorkflowIntent(str, Enum):
    COMPANY_RESEARCH = "company_research"
    MARKET_CONTEXT = "market_context"
    PORTFOLIO_STRESS = "portfolio_stress"
    STRATEGY_VALIDATION = "strategy_validation"


class WorkflowArtifactKind(str, Enum):
    RESEARCH_MEMO = "research_memo"
    MARKET_CONTEXT = "market_context"
    PORTFOLIO_RISK_REVIEW = "portfolio_risk_review"
    STRATEGY_VALIDATION_DOSSIER = "strategy_validation_dossier"
    REVIEW_ONLY_MEMO = "review_only_memo"
    DATA_QUALITY_REPORT = "data_quality_report"
    WORKFLOW_BLOCK_NOTICE = "workflow_block_notice"


class WorkflowStatus(str, Enum):
    COMPLETED = "completed"
    ATTENTION_REQUIRED = "attention_required"
    BLOCKED = "blocked"


class WorkflowBlockReason(str, Enum):
    USER_PAUSED = "user_paused"
    HARD_RISK = "hard_risk"


class WorkflowStage(BaseModel):
    model_config = ConfigDict(frozen=True)

    stage_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    title: str = Field(min_length=1, max_length=120)
    task_type: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    profile: ExecutionProfile
    agent_ids: list[str] = Field(min_length=1, max_length=43)


class WorkflowDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    workflow_key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    title: str = Field(min_length=1, max_length=160)
    artifact_kind: WorkflowArtifactKind
    completion_status: WorkflowStatus = WorkflowStatus.COMPLETED
    stages: list[WorkflowStage] = Field(min_length=1)


class WorkflowContext(BaseModel):
    """Business state used to select a safe workflow."""

    intent: WorkflowIntent
    subject: str = Field(min_length=1, max_length=500)
    asset_kind: AssetKind = AssetKind.OTHER
    evidence: list[EvidenceRecord] = Field(default_factory=list, max_length=50)
    available_resources: set[str] = Field(default_factory=set, max_length=32)
    authorized_actions: set[str] = Field(default_factory=set, max_length=16)
    stage_payloads: dict[str, dict[str, Any]] = Field(default_factory=dict)
    user_paused: bool = False
    hard_risk_blocked: bool = False
    cooldown_active: bool = False
    market_data_usable: bool = True
    mandate_active: bool = True


class WorkflowSelection(BaseModel):
    definition: WorkflowDefinition | None = None
    block_reason: WorkflowBlockReason | None = None
    rationale: str


class WorkflowStageRun(BaseModel):
    stage: WorkflowStage
    run: AgentRun


class ArtifactSection(BaseModel):
    title: str
    items: list[str] = Field(default_factory=list)


class WorkflowArtifact(BaseModel):
    artifact_kind: WorkflowArtifactKind
    status: WorkflowStatus
    workflow_id: str
    scenario: WorkflowIntent
    title: str
    summary: str
    sections: list[ArtifactSection] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    agent_ids: list[str] = Field(default_factory=list)
    routing_notices: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    generated_at: datetime

    def to_markdown(self) -> str:
        lines = [
            f"# {self.title}",
            "",
            f"- 产物类型：`{self.artifact_kind.value}`",
            f"- 状态：`{self.status.value}`",
            f"- 工作流：`{self.workflow_id}`",
            f"- 场景：`{self.scenario.value}`",
            f"- 生成时间：`{self.generated_at.isoformat()}`",
            "",
            "## 摘要",
            "",
            self.summary,
        ]
        for section in self.sections:
            lines.extend(["", f"## {section.title}", ""])
            lines.extend(f"- {item}" for item in section.items)
            if not section.items:
                lines.append("- 无")
        lines.extend(["", "## 证据与审计", ""])
        lines.append(
            "- 证据 ID："
            + (", ".join(f"`{item}`" for item in self.evidence_ids) or "无")
        )
        lines.append(
            "- 参与 Agent："
            + (", ".join(f"`{item}`" for item in self.agent_ids) or "无")
        )
        if self.routing_notices:
            lines.extend(f"- 路由提示：{item}" for item in self.routing_notices)
        lines.extend(["", "## 下一步", ""])
        lines.extend(f"- {item}" for item in self.next_steps)
        return "\n".join(lines) + "\n"


class WorkflowRun(BaseModel):
    workflow_id: str
    scenario: WorkflowIntent
    selected_workflow: str | None
    selection_rationale: str
    stage_runs: list[WorkflowStageRun] = Field(default_factory=list)
    artifact: WorkflowArtifact


class MultiAgentWorkflowExecutor(Protocol):
    async def execute_multi_agent(self, request: AgentRequest) -> AgentRun: ...


WORKFLOW_DEFINITIONS: dict[str, WorkflowDefinition] = {
    "company_research": WorkflowDefinition(
        workflow_key="company_research",
        title="公司深度研究",
        artifact_kind=WorkflowArtifactKind.RESEARCH_MEMO,
        stages=[
            WorkflowStage(
                stage_id="evidence_review",
                title="事实与公司结构审阅",
                task_type="research",
                profile=ExecutionProfile.RESEARCH,
                agent_ids=[
                    "tradingagents:fundamentals_analyst",
                    "tradingagents:market_analyst",
                    "tradingagents:news_analyst",
                    "finrobot:equity:CompanyOverviewAgent",
                    "finrobot:equity:CompetitorAnalysisAgent",
                    "finrobot:equity:ValuationOverviewAgent",
                ],
            ),
            WorkflowStage(
                stage_id="adversarial_review",
                title="正反观点与风险辩论",
                task_type="research",
                profile=ExecutionProfile.RESEARCH,
                agent_ids=[
                    "tradingagents:bull_researcher",
                    "tradingagents:bear_researcher",
                    "finrobot:equity:RiskAnalystAgent",
                    "tradingagents:aggressive_debator",
                    "tradingagents:neutral_debator",
                    "tradingagents:conservative_debator",
                ],
            ),
            WorkflowStage(
                stage_id="research_synthesis",
                title="研究结论与治理复核",
                task_type="research",
                profile=ExecutionProfile.RESEARCH,
                agent_ids=[
                    "tradingagents:research_manager",
                    "tradingagents:portfolio_manager",
                    "finrobot:equity:MajorTakeawaysAgent",
                ],
            ),
        ],
    ),
    "market_context": WorkflowDefinition(
        workflow_key="market_context",
        title="市场环境与风险状态",
        artifact_kind=WorkflowArtifactKind.MARKET_CONTEXT,
        stages=[
            WorkflowStage(
                stage_id="market_monitor",
                title="确定性市场状态监控",
                task_type="research",
                profile=ExecutionProfile.RESEARCH,
                agent_ids=["quantskills:agent-market-regime-monitor"],
            ),
            WorkflowStage(
                stage_id="market_interpretation",
                title="市场、新闻与情绪解释",
                task_type="research",
                profile=ExecutionProfile.RESEARCH,
                agent_ids=[
                    "tradingagents:market_analyst",
                    "tradingagents:news_analyst",
                    "tradingagents:sentiment_analyst",
                    "tradingagents:conservative_debator",
                ],
            ),
            WorkflowStage(
                stage_id="market_governance",
                title="市场结论治理复核",
                task_type="research",
                profile=ExecutionProfile.RESEARCH,
                agent_ids=[
                    "tradingagents:research_manager",
                    "tradingagents:portfolio_manager",
                ],
            ),
        ],
    ),
    "portfolio_stress": WorkflowDefinition(
        workflow_key="portfolio_stress",
        title="组合压力与拥挤风险审查",
        artifact_kind=WorkflowArtifactKind.PORTFOLIO_RISK_REVIEW,
        stages=[
            WorkflowStage(
                stage_id="correlation_monitor",
                title="相关性破裂监控",
                task_type="research",
                profile=ExecutionProfile.RESEARCH,
                agent_ids=["quantskills:agent-correlation-break-research"],
            ),
            WorkflowStage(
                stage_id="crowding_monitor",
                title="拥挤风险监控",
                task_type="research",
                profile=ExecutionProfile.RESEARCH,
                agent_ids=["quantskills:agent-crowding-risk-monitor"],
            ),
            WorkflowStage(
                stage_id="portfolio_risk_debate",
                title="组合风险辩论与治理",
                task_type="research",
                profile=ExecutionProfile.RESEARCH,
                agent_ids=[
                    "tradingagents:aggressive_debator",
                    "tradingagents:neutral_debator",
                    "tradingagents:conservative_debator",
                    "tradingagents:portfolio_manager",
                ],
            ),
        ],
    ),
    "strategy_validation": WorkflowDefinition(
        workflow_key="strategy_validation",
        title="量化策略开发与验证",
        artifact_kind=WorkflowArtifactKind.STRATEGY_VALIDATION_DOSSIER,
        stages=[
            WorkflowStage(
                stage_id="strategy_requirements",
                title="策略需求与验收条件",
                task_type="quant_development",
                profile=ExecutionProfile.WORKSPACE,
                agent_ids=["quantskills:liangshuyuan:analyst-agent"],
            ),
            WorkflowStage(
                stage_id="strategy_design",
                title="Alpha 设计",
                task_type="quant_development",
                profile=ExecutionProfile.WORKSPACE,
                agent_ids=["quantskills:liangshuyuan:dev-alpha-agent"],
            ),
            WorkflowStage(
                stage_id="strategy_backtest",
                title="回测与稳定性检查",
                task_type="backtest",
                profile=ExecutionProfile.WORKSPACE,
                agent_ids=["quantskills:agent-quantspace"],
            ),
            WorkflowStage(
                stage_id="strategy_test",
                title="验收测试",
                task_type="testing",
                profile=ExecutionProfile.WORKSPACE,
                agent_ids=["quantskills:liangshuyuan:test-agent"],
            ),
            WorkflowStage(
                stage_id="strategy_governance",
                title="策略治理汇总",
                task_type="quant_development",
                profile=ExecutionProfile.WORKSPACE,
                agent_ids=["quantskills:liangshuyuan:main-agent"],
            ),
        ],
    ),
    "review_only": WorkflowDefinition(
        workflow_key="review_only",
        title="只读复核与冷静期工作流",
        artifact_kind=WorkflowArtifactKind.REVIEW_ONLY_MEMO,
        completion_status=WorkflowStatus.ATTENTION_REQUIRED,
        stages=[
            WorkflowStage(
                stage_id="review_only_analysis",
                title="证据与下行风险复核",
                task_type="research",
                profile=ExecutionProfile.RESEARCH,
                agent_ids=[
                    "tradingagents:fundamentals_analyst",
                    "tradingagents:conservative_debator",
                    "tradingagents:research_manager",
                    "tradingagents:portfolio_manager",
                ],
            )
        ],
    ),
    "data_quality_review": WorkflowDefinition(
        workflow_key="data_quality_review",
        title="数据质量诊断",
        artifact_kind=WorkflowArtifactKind.DATA_QUALITY_REPORT,
        completion_status=WorkflowStatus.ATTENTION_REQUIRED,
        stages=[
            WorkflowStage(
                stage_id="data_quality_analysis",
                title="数据缺口与可用性诊断",
                task_type="research",
                profile=ExecutionProfile.RESEARCH,
                agent_ids=[
                    "finrobot:library:Data_Analyst",
                    "finrobot:library:Statistician",
                    "tradingagents:market_analyst",
                    "tradingagents:research_manager",
                ],
            )
        ],
    ),
}


class WorkflowSelector:
    """Select a workflow using the product's fixed safety priority."""

    def select(self, context: WorkflowContext) -> WorkflowSelection:
        if context.user_paused:
            return WorkflowSelection(
                block_reason=WorkflowBlockReason.USER_PAUSED,
                rationale="用户暂停优先于所有 Agent 工作流。",
            )
        if context.hard_risk_blocked:
            return WorkflowSelection(
                block_reason=WorkflowBlockReason.HARD_RISK,
                rationale="硬风控阻断，不能继续生成策略或执行型产物。",
            )
        if context.cooldown_active and context.intent in {
            WorkflowIntent.PORTFOLIO_STRESS,
            WorkflowIntent.STRATEGY_VALIDATION,
        }:
            return WorkflowSelection(
                definition=WORKFLOW_DEFINITIONS["review_only"],
                rationale="冷静期内降级为只读复核，不生成执行型建议。",
            )
        if (
            not context.market_data_usable
            and context.intent != WorkflowIntent.COMPANY_RESEARCH
        ):
            return WorkflowSelection(
                definition=WORKFLOW_DEFINITIONS["data_quality_review"],
                rationale="市场数据不可用，切换为数据质量诊断并停止策略链路。",
            )
        if (
            not context.mandate_active
            and context.intent == WorkflowIntent.STRATEGY_VALIDATION
        ):
            return WorkflowSelection(
                definition=WORKFLOW_DEFINITIONS["review_only"],
                rationale="授权书无效，仅允许只读复核。",
            )
        workflow_key = {
            WorkflowIntent.COMPANY_RESEARCH: "company_research",
            WorkflowIntent.MARKET_CONTEXT: "market_context",
            WorkflowIntent.PORTFOLIO_STRESS: "portfolio_stress",
            WorkflowIntent.STRATEGY_VALIDATION: "strategy_validation",
        }[context.intent]
        return WorkflowSelection(
            definition=WORKFLOW_DEFINITIONS[workflow_key],
            rationale=f"业务状态满足 {workflow_key} 工作流的执行前提。",
        )


class WorkflowExecutor:
    """Execute selected workflow stages and preserve evidence between stages."""

    def __init__(
        self,
        orchestrator: MultiAgentWorkflowExecutor,
        *,
        selector: WorkflowSelector | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._selector = selector or WorkflowSelector()

    async def execute(
        self,
        *,
        workflow_id: str,
        context: WorkflowContext,
    ) -> WorkflowRun:
        self._validate_workflow_id(workflow_id)
        selection = self._selector.select(context)
        if selection.block_reason is not None:
            artifact = self._blocked_artifact(
                workflow_id=workflow_id,
                context=context,
                selection=selection,
                generated_at=datetime.now(timezone.utc),
            )
            return WorkflowRun(
                workflow_id=workflow_id,
                scenario=context.intent,
                selected_workflow=None,
                selection_rationale=selection.rationale,
                artifact=artifact,
            )

        definition = selection.definition
        if definition is None:
            raise RuntimeError(
                "Workflow selection returned neither definition nor block reason"
            )

        evidence = list(context.evidence)
        known_evidence_ids = {item.identifier for item in evidence}
        stage_runs: list[WorkflowStageRun] = []
        for stage_index, stage in enumerate(definition.stages, start=1):
            request = AgentRequest(
                run_id=f"{workflow_id}-s{stage_index}",
                subject=context.subject,
                task_type=stage.task_type,
                profile=stage.profile,
                asset_kind=context.asset_kind,
                available_resources=context.available_resources,
                authorized_actions=context.authorized_actions,
                requested_agent_ids=stage.agent_ids,
                evidence=evidence,
                payload=context.stage_payloads.get(stage.stage_id, {}),
                max_agents=len(stage.agent_ids),
            )
            run = await self._orchestrator.execute_multi_agent(request)
            stage_runs.append(WorkflowStageRun(stage=stage, run=run))
            self._extend_evidence(
                evidence=evidence,
                known_ids=known_evidence_ids,
                stage_index=stage_index,
                run=run,
            )

        artifact = self._completed_artifact(
            workflow_id=workflow_id,
            context=context,
            selection=selection,
            definition=definition,
            stage_runs=stage_runs,
            generated_at=datetime.now(timezone.utc),
        )
        return WorkflowRun(
            workflow_id=workflow_id,
            scenario=context.intent,
            selected_workflow=definition.workflow_key,
            selection_rationale=selection.rationale,
            stage_runs=stage_runs,
            artifact=artifact,
        )

    @staticmethod
    def _validate_workflow_id(workflow_id: str) -> None:
        if (
            not _WORKFLOW_ID_PATTERN.fullmatch(workflow_id)
            or len(workflow_id) > _MAX_WORKFLOW_ID_LENGTH
        ):
            raise ValueError(
                "workflow_id must contain only letters, numbers, underscores, or hyphens "
                f"and be at most {_MAX_WORKFLOW_ID_LENGTH} characters"
            )

    @staticmethod
    def _extend_evidence(
        *,
        evidence: list[EvidenceRecord],
        known_ids: set[str],
        stage_index: int,
        run: AgentRun,
    ) -> None:
        for result_index, result in enumerate(run.results, start=1):
            for record in result.evidence:
                if record.identifier not in known_ids:
                    evidence.append(record)
                    known_ids.add(record.identifier)
            identifier = f"WF_S{stage_index}_A{result_index}"
            if identifier in known_ids:
                raise ValueError(
                    f"duplicate workflow evidence identifier: {identifier}"
                )
            evidence.append(
                EvidenceRecord(
                    identifier=identifier,
                    source=f"Agent output: {result.agent_id}"[:256],
                    excerpt=result.summary[:4_000],
                )
            )
            known_ids.add(identifier)

    @staticmethod
    def _completed_artifact(
        *,
        workflow_id: str,
        context: WorkflowContext,
        selection: WorkflowSelection,
        definition: WorkflowDefinition,
        stage_runs: list[WorkflowStageRun],
        generated_at: datetime,
    ) -> WorkflowArtifact:
        results = [
            result for stage_run in stage_runs for result in stage_run.run.results
        ]
        final_results = stage_runs[-1].run.results
        summary = "；".join(result.summary for result in final_results)
        claims = [
            f"[{claim.author_agent_id}] {claim.statement}"
            for result in results
            for claim in result.claims
        ]
        limitations = sorted(
            {
                item
                for result in results
                for claim in result.claims
                for item in [*claim.unknowns, *claim.invalidation_conditions]
            }
        )
        proposed_actions = sorted(
            {item for result in results for item in result.proposed_actions}
        )
        contributions = [f"{result.agent_id}: {result.summary}" for result in results]
        evidence_ids = sorted(
            {
                evidence_id
                for result in results
                for claim in result.claims
                for evidence_id in claim.evidence_ids
            }
            | {record.identifier for result in results for record in result.evidence}
        )
        notices = [
            f"{notice.agent_id}: {notice.reason}"
            for stage_run in stage_runs
            for notice in stage_run.run.plan.notices
        ]
        next_steps = proposed_actions or [
            "由人工审核证据、限制与失效条件；本产物不自动创建订单或改变授权。"
        ]
        return WorkflowArtifact(
            artifact_kind=definition.artifact_kind,
            status=definition.completion_status,
            workflow_id=workflow_id,
            scenario=context.intent,
            title=f"{definition.title}：{context.subject}",
            summary=summary,
            sections=[
                ArtifactSection(title="证据支持的判断", items=claims),
                ArtifactSection(title="未知项与失效条件", items=limitations),
                ArtifactSection(title="Agent 贡献", items=contributions),
                ArtifactSection(title="待审核动作（未执行）", items=proposed_actions),
            ],
            evidence_ids=evidence_ids,
            agent_ids=[result.agent_id for result in results],
            routing_notices=notices,
            next_steps=next_steps,
            generated_at=generated_at,
        )

    @staticmethod
    def _blocked_artifact(
        *,
        workflow_id: str,
        context: WorkflowContext,
        selection: WorkflowSelection,
        generated_at: datetime,
    ) -> WorkflowArtifact:
        reason = selection.block_reason
        if reason is None:
            raise RuntimeError("Blocked artifact requires a block reason")
        next_step = {
            WorkflowBlockReason.USER_PAUSED: "由用户明确恢复 Agent 后重新创建工作流。",
            WorkflowBlockReason.HARD_RISK: "先处理硬风控事件，并通过独立风控复核。",
        }[reason]
        return WorkflowArtifact(
            artifact_kind=WorkflowArtifactKind.WORKFLOW_BLOCK_NOTICE,
            status=WorkflowStatus.BLOCKED,
            workflow_id=workflow_id,
            scenario=context.intent,
            title=f"工作流阻断通知：{context.subject}",
            summary=selection.rationale,
            sections=[
                ArtifactSection(title="阻断原因", items=[reason.value]),
                ArtifactSection(
                    title="未执行范围",
                    items=["未调用任何 Agent；未生成策略、组合或订单意图。"],
                ),
            ],
            evidence_ids=[item.identifier for item in context.evidence],
            next_steps=[next_step],
            generated_at=generated_at,
        )
