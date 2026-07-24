import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def new_id() -> str:
    return str(uuid.uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc)


class OnboardingSession(Base):
    __tablename__ = "onboarding_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    live_key: Mapped[str | None] = mapped_column(String(36), unique=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    __mapper_args__ = {"version_id_col": row_version}
    step: Mapped[str] = mapped_column(String(32), default="objective_profile", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="active", nullable=False, index=True)
    round_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    turn_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    min_rounds: Mapped[int] = mapped_column(Integer, default=6, nullable=False)
    max_rounds: Mapped[int] = mapped_column(Integer, default=12, nullable=False)
    completeness: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    provider_name: Mapped[str] = mapped_column(String(64), default="mock", nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), default="mock", nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), default="v1", nullable=False)
    prompt_id: Mapped[str | None] = mapped_column(ForeignKey("prompt_versions.id"))
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_content: Mapped[str] = mapped_column(Text, nullable=False)
    objective_profile: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    dimension_scores: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    profile_evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    skipped_dimensions: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    followup_counts: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    current_dimension: Mapped[str | None] = mapped_column(String(64))
    current_question: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProfileMessage(Base):
    __tablename__ = "profile_messages"
    __table_args__ = (UniqueConstraint("session_id", "request_id", name="uq_profile_messages_request"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("onboarding_sessions.id"), nullable=False, index=True)
    request_id: Mapped[str | None] = mapped_column(String(36))
    parent_message_id: Mapped[str | None] = mapped_column(ForeignKey("profile_messages.id"))
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    input_mode: Mapped[str] = mapped_column(String(16), default="text", nullable=False)
    target_dimension: Mapped[str | None] = mapped_column(String(64))
    sensitive: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    refused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    extracted_data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
