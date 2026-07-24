import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def new_id() -> str:
    return str(uuid.uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc)


class InvestmentProfile(Base):
    __tablename__ = "investment_profiles"
    __table_args__ = (
        UniqueConstraint("user_id", "version", name="uq_investment_profiles_user_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("onboarding_sessions.id"), nullable=False, unique=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    objective_profile: Mapped[dict] = mapped_column(JSON, nullable=False)
    dimension_scores: Mapped[dict] = mapped_column(JSON, nullable=False)
    profile_evidence: Mapped[dict] = mapped_column(JSON, nullable=False)
    archetype_code: Mapped[str] = mapped_column(String(64), nullable=False)
    archetype_title: Mapped[str] = mapped_column(String(100), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False)
    loss_tolerance_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    completeness: Mapped[float] = mapped_column(Float, nullable=False)
    education_only: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    report_summary: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class DirectionRecommendation(Base):
    __tablename__ = "direction_recommendations"
    __table_args__ = (
        UniqueConstraint(
            "profile_id", "direction", name="uq_direction_recommendations_direction"
        ),
        UniqueConstraint(
            "profile_id", "rank", name="uq_direction_recommendations_rank"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    profile_id: Mapped[str] = mapped_column(ForeignKey("investment_profiles.id"), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(64), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actionable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    selected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    selected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
