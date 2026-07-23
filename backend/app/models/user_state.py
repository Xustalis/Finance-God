"""用户心智状态快照表"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import String, DateTime, Integer, Text, UniqueConstraint, Numeric
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class UserStateSnapshot(Base):
    __tablename__ = "user_state_snapshots"
    __table_args__ = (UniqueConstraint("user_id", "version", name="uq_state_user_version"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    mental_state: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    cognitive_biases: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    signal_sources: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    consent_scope: Mapped[str] = mapped_column(String(255), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    user_confirmation: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")  # pending/confirmed/corrected/rejected
    user_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
