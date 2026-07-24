"""Simulation-only order execution; this package has no live broker path."""

from .contracts import (
    CostEstimate,
    DraftMode,
    ExecutionFailure,
    ExecutionFailureCode,
    ManualReviewResult,
    OrderTimelineEntry,
    SimulationBar,
    SimulationFill,
    StoredDraft,
    StoredOrder,
    StoredOrderView,
    SubmissionOutcome,
    SubmissionStatus,
)
from .matcher import DeterministicMatcher, MatchResult, SimulationRuleSet
from .service import SimulationExecutionService

__all__ = [
    "CostEstimate",
    "DeterministicMatcher",
    "DraftMode",
    "ExecutionFailure",
    "ExecutionFailureCode",
    "ManualReviewResult",
    "MatchResult",
    "OrderTimelineEntry",
    "SimulationBar",
    "SimulationExecutionService",
    "SimulationFill",
    "SimulationRuleSet",
    "StoredDraft",
    "StoredOrder",
    "StoredOrderView",
    "SubmissionOutcome",
    "SubmissionStatus",
]
