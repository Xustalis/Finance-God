"""Simulation-only order execution; this package has no live broker path."""

from .contracts import (
    DraftMode,
    ExecutionFailure,
    ExecutionFailureCode,
    ManualReviewResult,
    SimulationBar,
    SimulationFill,
    StoredDraft,
    StoredOrder,
    SubmissionOutcome,
    SubmissionStatus,
)
from .matcher import DeterministicMatcher, MatchResult, SimulationRuleSet
from .service import SimulationExecutionService

__all__ = [
    "DeterministicMatcher",
    "DraftMode",
    "ExecutionFailure",
    "ExecutionFailureCode",
    "ManualReviewResult",
    "MatchResult",
    "SimulationBar",
    "SimulationExecutionService",
    "SimulationFill",
    "SimulationRuleSet",
    "StoredDraft",
    "StoredOrder",
    "SubmissionOutcome",
    "SubmissionStatus",
]
