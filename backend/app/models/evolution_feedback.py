"""自进化反馈表 - 第18张表"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Integer, Boolean, Text, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class EvolutionFeedback(Base):
    __tablename__ = "evolution_feedbacks"
    __table_args__ = (
        Index("ix_evolution_user_type", "user_id", "feedback_type"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)
    feedback_type: Mapped[str] = mapped_column(String(32), nullable=False)  # profile_correction/strategy_evaluation/bias_confirmation/bias_rejection
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)  # profile_dimension/strategy_proposal/cognitive_bias
    target_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    target_version: Mapped[int] = mapped_column(Integer, nullable=False)
    feedback_value: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    evolution_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
