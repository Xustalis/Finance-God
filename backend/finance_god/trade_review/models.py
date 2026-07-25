from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EpisodeStatus(StrEnum):
    OPEN = "open"
    CLOSED_PENDING_REVIEW = "closed_pending_review"
    REVIEW_COMPLETED = "review_completed"
    REVIEW_FAILED = "review_failed"


class ReviewStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class Availability(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class DecisionField(FrozenModel):
    status: Availability
    value: str | None = None
    unavailable_reason: str | None = None


class TradeEpisode(FrozenModel):
    episode_id: str
    owner_id: str
    account_id: str
    instrument_id: str
    status: EpisodeStatus
    review_status: ReviewStatus | None = None
    opened_at: datetime
    closed_at: datetime | None = None
    opening_quantity: Decimal = Field(gt=0)
    current_quantity: Decimal = Field(ge=0)
    revision: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime


class TradeDecisionSnapshot(FrozenModel):
    snapshot_id: str
    episode_id: str
    owner_id: str
    order_id: str
    fill_id: str
    instrument_id: str
    side: str
    quantity: Decimal = Field(gt=0)
    price: Decimal = Field(gt=0)
    fee: Decimal = Field(ge=0)
    occurred_at: datetime
    market_evidence: dict[str, str]
    profile_version: int | None = None
    research_references: tuple[dict[str, str], ...] = ()
    trade_plan_reference: dict[str, str] | None = None
    agent_decision_reference: dict[str, str] | None = None
    thesis: DecisionField
    expected_return: DecisionField
    primary_risks: DecisionField
    contrary_evidence: DecisionField
    expected_holding_period: DecisionField
    confidence: DecisionField
    snapshot_version: int = 1
    created_at: datetime


class TradeReview(FrozenModel):
    review_id: str
    episode_id: str
    owner_id: str
    status: ReviewStatus
    kind: str = "final"
    expected_return_assessment: str
    actual_return_rmb: Decimal
    actual_return_percent: Decimal | None = None
    holding_period_seconds: int = Field(ge=0)
    execution_assessment: str
    established_points: tuple[str, ...] = ()
    failed_points: tuple[str, ...] = ()
    unknown_points: tuple[str, ...] = ()
    next_adjustments: tuple[str, ...] = ()
    evidence_references: tuple[dict[str, str], ...] = ()
    profile_feedback_id: str | None = None
    error: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class ProfileFeedback(FrozenModel):
    feedback_id: str
    owner_id: str
    episode_id: str
    review_id: str
    parent_profile_version: int | None = None
    new_profile_version: int | None = None
    changed_dimensions: tuple[str, ...] = ()
    summary: str
    created_at: datetime
