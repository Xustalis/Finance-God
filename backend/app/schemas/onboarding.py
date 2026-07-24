from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator, model_validator


class Gender(StrEnum):
    MALE = "male"
    FEMALE = "female"
    NONBINARY = "nonbinary"
    PREFER_NOT_TO_SAY = "prefer_not_to_say"


class AgeRange(StrEnum):
    MINOR = "minor"
    AGE_18_25 = "18-25"
    AGE_26_35 = "26-35"
    AGE_36_45 = "36-45"
    AGE_46_55 = "46-55"
    AGE_56_65 = "56-65"
    AGE_65_PLUS = "65+"


class InputMode(StrEnum):
    TEXT = "text"
    VOICE = "voice"


class SessionStep(StrEnum):
    OBJECTIVE_PROFILE = "objective_profile"
    CONVERSATION = "conversation"
    READY = "ready"
    REPORT = "report"


class SessionStatus(StrEnum):
    ACTIVE = "active"
    READY = "ready"
    COMPLETED = "completed"


class AssetLevel(StrEnum):
    A1 = "A1"
    A2 = "A2"
    A3 = "A3"
    A4 = "A4"
    A5 = "A5"
    A6 = "A6"
    A7 = "A7"
    A8 = "A8"
    A9 = "A9"
    A10 = "A10"


class EmploymentStatus(StrEnum):
    EMPLOYED = "employed"
    SELF_EMPLOYED = "self_employed"
    UNEMPLOYED = "unemployed"
    STUDENT = "student"
    RETIRED = "retired"
    OTHER = "other"


class IncomeRange(StrEnum):
    I1 = "I1"
    I2 = "I2"
    I3 = "I3"
    I4 = "I4"
    I5 = "I5"
    I6 = "I6"
    I7 = "I7"
    I8 = "I8"
    I9 = "I9"
    I10 = "I10"


class DebtPressure(StrEnum):
    NONE = "none"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class InvestmentExperience(StrEnum):
    NONE = "none"
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class FundHorizon(StrEnum):
    UNDER_1_YEAR = "under_1_year"
    YEARS_1_3 = "1_3_years"
    YEARS_3_5 = "3_5_years"
    YEARS_5_PLUS = "5_plus_years"


class LossReaction(StrEnum):
    SELL_ALL = "sell_all"
    REDUCE = "reduce"
    HOLD = "hold"
    BUY_MORE = "buy_more"


class InvestmentDirection(StrEnum):
    CASH_FIXED_INCOME = "cash_fixed_income"
    PUBLIC_FUNDS = "public_funds"
    EQUITIES = "equities"
    ALTERNATIVES = "alternatives"
    LONG_TERM_INSURANCE = "long_term_insurance"


class ProfileDimension(StrEnum):
    RISK_TOLERANCE = "risk_tolerance"
    LIQUIDITY_NEED = "liquidity_need"
    INVESTMENT_GOAL = "investment_goal"
    LOSS_BEHAVIOR = "loss_behavior"
    INVESTMENT_KNOWLEDGE = "investment_knowledge"
    INCOME_STABILITY = "income_stability"


class ObjectiveProfileInput(BaseModel):
    gender: Gender
    age_range: AgeRange
    asset_level: AssetLevel
    employment_status: EmploymentStatus
    income_range: IncomeRange
    debt_pressure: DebtPressure
    emergency_fund_months: int = Field(ge=0, le=120)
    investment_experience: InvestmentExperience
    fund_horizon: FundHorizon
    loss_reaction: LossReaction


class MessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID | None = None
    content: str = Field(min_length=1, max_length=4000)
    input_mode: InputMode = InputMode.TEXT

    @field_validator("content")
    @classmethod
    def reject_blank_content(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("content cannot be blank")
        return stripped


class SkipInput(BaseModel):
    dimension: ProfileDimension


class DirectionSelectionInput(BaseModel):
    selected_direction: InvestmentDirection


class AITurnResult(BaseModel):
    reply: str = Field(min_length=1, max_length=4000)
    target_dimension: ProfileDimension
    sensitive: bool = False
    profile_delta: dict[ProfileDimension, float] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    should_continue: bool
    end_reason: str | None = None
    next_question: str | None = Field(default=None, min_length=1, max_length=1000)
    next_question_dimension: ProfileDimension | None = None
    retry_question: str = Field(min_length=1, max_length=1000)

    @field_validator("reply")
    @classmethod
    def reject_blank_reply(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reply cannot be blank")
        return value.strip()

    @model_validator(mode="after")
    def validate_profile_delta(self):
        if any(value < -1.0 or value > 1.0 for value in self.profile_delta.values()):
            raise ValueError("profile_delta values must be between -1 and 1")
        if any(key != self.target_dimension for key in self.profile_delta):
            raise ValueError("profile_delta may only update target_dimension")
        if (self.next_question is None) != (self.next_question_dimension is None):
            raise ValueError("next_question and next_question_dimension must both be set or both be null")
        return self

    @field_validator("next_question", "retry_question")
    @classmethod
    def normalize_question(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("question cannot be blank")
        return stripped


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    step: SessionStep
    status: SessionStatus
    round_count: int
    turn_count: int
    row_version: int
    min_rounds: int
    max_rounds: int
    completeness: float
    provider_name: str
    model_name: str
    prompt_version: str
    prompt_id: str | None
    prompt_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    objective_profile: ObjectiveProfileInput | None
    dimension_scores: "ConversationDimensionScores"
    profile_evidence: "ProfileEvidence"
    skipped_dimensions: list[ProfileDimension]
    followup_counts: "FollowupCounts"
    current_dimension: ProfileDimension | None
    current_question: str | None

    @field_validator("objective_profile", mode="before")
    @classmethod
    def empty_objective_is_none(cls, value):
        return value or None

class MessageReference(BaseModel):
    id: str
    content: str
    input_mode: InputMode | None = None


class MessageTurnResponse(BaseModel):
    session: SessionResponse
    user_message: MessageReference
    assistant_message: MessageReference
    turn: AITurnResult


class ConversationDimensionScores(RootModel[dict[ProfileDimension, Annotated[float, Field(ge=0, le=1)]]]):
    pass


class ProfileEvidence(RootModel[dict[ProfileDimension, Annotated[float, Field(ge=-1, le=1)]]]):
    pass


class FollowupCounts(RootModel[dict[ProfileDimension, Annotated[int, Field(ge=0, le=2)]]]):
    pass


class RiskLevel(StrEnum):
    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    GROWTH = "growth"


class ArchetypeCode(StrEnum):
    STEADY_GUARDIAN = "STEADY_GUARDIAN"
    BALANCED_NAVIGATOR = "BALANCED_NAVIGATOR"
    LONG_HORIZON_BUILDER = "LONG_HORIZON_BUILDER"


class ProfileDimensionScores(BaseModel):
    risk_capacity: int = Field(ge=0, le=100)
    liquidity_resilience: int = Field(ge=0, le=100)
    experience: int = Field(ge=0, le=100)
    risk_tolerance: int | None = Field(default=None, ge=0, le=100)
    liquidity_need: int | None = Field(default=None, ge=0, le=100)
    investment_goal: int | None = Field(default=None, ge=0, le=100)
    loss_behavior: int | None = Field(default=None, ge=0, le=100)
    investment_knowledge: int | None = Field(default=None, ge=0, le=100)
    income_stability: int | None = Field(default=None, ge=0, le=100)


class ProfileReportSummary(BaseModel):
    traits: list[str] = Field(max_length=5)
    risk_notice: str
    reasoning: list[str]
    low_confidence: list[ProfileDimension]


class ProfileResponse(BaseModel):
    id: str
    user_id: str
    session_id: str
    version: int
    objective_profile: ObjectiveProfileInput
    dimension_scores: ProfileDimensionScores
    profile_evidence: ProfileEvidence
    archetype_code: ArchetypeCode
    archetype_title: str
    risk_level: RiskLevel
    loss_tolerance_percent: int
    confidence: float
    completeness: float
    education_only: bool
    report_summary: ProfileReportSummary


class DirectionRecommendationResponse(BaseModel):
    id: str
    direction: InvestmentDirection
    score: float
    rank: int
    reason: str
    actionable: bool
    selected: bool


class ProfileWithRecommendationsResponse(BaseModel):
    profile: ProfileResponse
    recommendations: list[DirectionRecommendationResponse]


class DirectionSelectionResponse(DirectionRecommendationResponse):
    selected_direction: InvestmentDirection
