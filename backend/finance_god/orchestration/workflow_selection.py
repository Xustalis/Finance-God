"""Deterministic workflow selection with product safety priority."""

from __future__ import annotations

from pydantic import Field, model_validator

from finance_god.agents.contracts import OrderReviewMode, WorkflowKey
from finance_god.domain.models import (
    VersionReference,
    WorkflowBlockReason,
)

from .workflow_registry import FrozenModel


class WorkflowRoutingContext(FrozenModel):
    requested_workflow: WorkflowKey
    request_intent: str = Field(min_length=1, max_length=500)
    owner_id: str = Field(min_length=1, max_length=160)
    scope: dict[str, str] = Field(default_factory=dict)
    input_versions: tuple[VersionReference, ...] = Field(min_length=1)
    user_paused: bool = False
    hard_risk_blocked: bool = False
    cooldown_active: bool = False
    data_usable: bool = True
    market_usable: bool = True
    authorization_active: bool = True
    agent_runtime_available: bool = True
    order_review_mode: OrderReviewMode | None = None
    manual_risk_reducing: bool = False

    @model_validator(mode="after")
    def validate_manual_mode(self) -> WorkflowRoutingContext:
        if self.order_review_mode is not None and (
            self.requested_workflow is not WorkflowKey.ORDER_REVIEW
        ):
            raise ValueError("order review mode belongs only to order_review")
        if self.manual_risk_reducing and (
            self.requested_workflow is not WorkflowKey.ORDER_REVIEW
            or self.order_review_mode is not OrderReviewMode.MANUAL
        ):
            raise ValueError("manual risk reduction requires manual order_review")
        return self


class WorkflowBlockNotice(FrozenModel):
    notice_id: str = Field(pattern=r"^[A-Za-z0-9_-]+$", max_length=160)
    requested_workflow: WorkflowKey
    reason: WorkflowBlockReason
    rationale: str = Field(min_length=1, max_length=500)
    owner_id: str = Field(min_length=1, max_length=160)
    scope: dict[str, str]
    input_versions: tuple[VersionReference, ...]
    agent_calls: int = Field(default=0, frozen=True)
    pending_actions_executed: bool = Field(default=False, frozen=True)


class WorkflowSelection(FrozenModel):
    selected_workflow: WorkflowKey | None
    rationale: str = Field(min_length=1, max_length=500)
    block_notice: WorkflowBlockNotice | None = None
    suppress_agent_nodes: bool = False

    @model_validator(mode="after")
    def validate_result(self) -> WorkflowSelection:
        if (self.selected_workflow is None) == (self.block_notice is None):
            raise ValueError(
                "selection requires exactly one workflow or block notice"
            )
        if self.block_notice is not None and self.suppress_agent_nodes:
            raise ValueError("blocked selection has no executable nodes")
        return self


class WorkflowSelector:
    """Priority: pause > hard risk > cooldown > data/market > auth > normal."""

    def select(
        self,
        context: WorkflowRoutingContext,
        *,
        notice_id: str,
    ) -> WorkflowSelection:
        manual_order_review = (
            context.requested_workflow is WorkflowKey.ORDER_REVIEW
            and context.order_review_mode is OrderReviewMode.MANUAL
        )
        suppress_manual_agents = context.user_paused and manual_order_review
        if context.user_paused and not manual_order_review:
            return self._blocked(
                context,
                notice_id=notice_id,
                reason=WorkflowBlockReason.USER_PAUSED,
                rationale="用户暂停优先于所有新 Agent 工作流。",
            )
        if context.hard_risk_blocked:
            return self._blocked(
                context,
                notice_id=notice_id,
                reason=WorkflowBlockReason.HARD_RISK,
                rationale="硬风控阻断新增风险行为和执行链路。",
            )
        if context.cooldown_active:
            if manual_order_review and context.manual_risk_reducing:
                return WorkflowSelection(
                    selected_workflow=WorkflowKey.ORDER_REVIEW,
                    rationale=(
                        "冷静期仅允许风险降低型手动订单执行确定性复核。"
                    ),
                    suppress_agent_nodes=True,
                )
            return WorkflowSelection(
                selected_workflow=WorkflowKey.REVIEW_ONLY,
                rationale="冷静期仅允许只读复核。",
                suppress_agent_nodes=suppress_manual_agents,
            )
        if not context.data_usable or not context.market_usable:
            return WorkflowSelection(
                selected_workflow=WorkflowKey.DATA_QUALITY_REVIEW,
                rationale="数据或市场状态不可用，进入数据质量诊断。",
                suppress_agent_nodes=suppress_manual_agents,
            )
        if not context.authorization_active:
            return WorkflowSelection(
                selected_workflow=WorkflowKey.REVIEW_ONLY,
                rationale="授权无效，只允许只读复核。",
                suppress_agent_nodes=suppress_manual_agents,
            )
        if manual_order_review and not context.agent_runtime_available:
            suppress_manual_agents = True
        if suppress_manual_agents:
            return WorkflowSelection(
                selected_workflow=WorkflowKey.ORDER_REVIEW,
                rationale="Agent 已暂停或不可用；手动订单继续执行确定性正式复核。",
                suppress_agent_nodes=True,
            )
        return WorkflowSelection(
            selected_workflow=context.requested_workflow,
            rationale=(
                f"安全门通过，选择 {context.requested_workflow.value}。"
            ),
        )

    @staticmethod
    def _blocked(
        context: WorkflowRoutingContext,
        *,
        notice_id: str,
        reason: WorkflowBlockReason,
        rationale: str,
    ) -> WorkflowSelection:
        return WorkflowSelection(
            selected_workflow=None,
            rationale=rationale,
            block_notice=WorkflowBlockNotice(
                notice_id=notice_id,
                requested_workflow=context.requested_workflow,
                reason=reason,
                rationale=rationale,
                owner_id=context.owner_id,
                scope=context.scope,
                input_versions=context.input_versions,
            ),
        )
