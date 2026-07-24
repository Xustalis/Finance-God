"""Public workflow facade backed by the governed fifteen-workflow runtime.

This module intentionally contains no workflow state model.  ``WorkflowRun`` and
``WorkflowRunStatus`` are re-exported from the domain package so callers cannot
accidentally create a parallel orchestration state source.
"""

from __future__ import annotations

from enum import StrEnum

from finance_god.agents.catalog import AgentGovernanceCatalog
from finance_god.agents.contracts import WorkflowKey
from finance_god.domain.models import (
    VersionReference,
    WorkflowBlockReason,
    WorkflowRun,
    WorkflowRunStatus,
)

from .task_plans import DynamicTaskPlanValidator, TaskPlan, TaskPlanFactory
from .workflow_commands import (
    DataQualityWorkflowCreationPort,
    WorkflowCommandPort,
    WorkflowCommandService,
    WorkflowCreateCommand,
    WorkflowCreationReceipt,
    WorkflowRunRepository,
)
from .workflow_executor import (
    NodeExecutionContext,
    NodeExecutionError,
    NodeExecutionOutcome,
    WorkflowControlPort,
    WorkflowControlState,
    WorkflowExecutionReport,
    WorkflowExecutor,
    WorkflowNodeRunner,
)
from .workflow_registry import (
    WORKFLOW_REGISTRY_VERSION,
    DeterministicResultContract,
    FormalWorkflowRegistry,
    InputQualityGate,
    WorkflowDefinition,
    WorkflowNodeDefinition,
    WorkflowNodeKind,
)
from .workflow_results import (
    DeterministicNodeResult,
    OrderRiskCheckNodeResult,
    SimulationFactNodeResult,
)
from .workflow_selection import (
    WorkflowBlockNotice,
    WorkflowRoutingContext,
    WorkflowSelection,
    WorkflowSelector,
)
from .workflow_runtime import (
    WorkflowCommandRuntime,
    create_workflow_command_runtime_from_environment,
)


class WorkflowArtifactKind(StrEnum):
    """Compatibility labels for the versioned final-artifact contracts."""

    RESEARCH_MEMO = "ResearchMemo"
    MARKET_CONTEXT = "MarketContext"
    PORTFOLIO_RISK_REVIEW = "PortfolioRiskReview"
    STRATEGY_VALIDATION_DOSSIER = "StrategyValidationDossier"
    REVIEW_ONLY_MEMO = "ReviewOnlyMemo"
    DATA_QUALITY_REPORT = "DataQualityReport"
    FUND_RESEARCH_REPORT = "FundResearchReport"
    PORTFOLIO_PROPOSAL = "PortfolioProposal"
    TRADE_PLAN = "TradePlan"
    ORDER_REVIEW_MEMO = "OrderReviewMemo"
    EXECUTION_RUN = "ExecutionRun"
    TRADE_REVIEW = "TradeReview"
    EVENT_IMPACT_REPORT = "EventImpactReport"
    CROSS_MARKET_REPORT = "CrossMarketReport"
    STRATEGY_MONITOR_REPORT = "StrategyMonitorReport"


WORKFLOW_REGISTRY = FormalWorkflowRegistry.build_default(
    AgentGovernanceCatalog()
)
WORKFLOW_DEFINITIONS = WORKFLOW_REGISTRY.as_mapping()

# Import-compatible names from the six-workflow prototype.  They are aliases to
# governed domain/contracts, not duplicate models or state machines.
WorkflowIntent = WorkflowKey
WorkflowStatus = WorkflowRunStatus
WorkflowContext = WorkflowRoutingContext
WorkflowArtifact = VersionReference

__all__ = [
    "WORKFLOW_DEFINITIONS",
    "WORKFLOW_REGISTRY",
    "WORKFLOW_REGISTRY_VERSION",
    "DataQualityWorkflowCreationPort",
    "DeterministicNodeResult",
    "DeterministicResultContract",
    "DynamicTaskPlanValidator",
    "FormalWorkflowRegistry",
    "InputQualityGate",
    "NodeExecutionContext",
    "NodeExecutionError",
    "NodeExecutionOutcome",
    "OrderRiskCheckNodeResult",
    "SimulationFactNodeResult",
    "TaskPlan",
    "TaskPlanFactory",
    "WorkflowArtifact",
    "WorkflowArtifactKind",
    "WorkflowBlockNotice",
    "WorkflowBlockReason",
    "WorkflowCommandPort",
    "WorkflowCommandRuntime",
    "WorkflowCommandService",
    "WorkflowContext",
    "WorkflowControlPort",
    "WorkflowControlState",
    "WorkflowCreateCommand",
    "WorkflowCreationReceipt",
    "WorkflowDefinition",
    "WorkflowExecutionReport",
    "WorkflowExecutor",
    "WorkflowIntent",
    "WorkflowKey",
    "WorkflowNodeDefinition",
    "WorkflowNodeKind",
    "WorkflowNodeRunner",
    "WorkflowRoutingContext",
    "WorkflowRun",
    "WorkflowRunRepository",
    "WorkflowSelection",
    "WorkflowSelector",
    "WorkflowStatus",
    "create_workflow_command_runtime_from_environment",
]
