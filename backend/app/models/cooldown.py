"""冷静期表"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CooldownPeriod(Base):
    __tablename__ = "cooldown_periods"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)
    trigger_state_snapshot_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    trigger_reason: Mapped[str] = mapped_column(Text, nullable=False)
    cooldown_type: Mapped[str] = mapped_column(String(32), nullable=False)  # anxiety/impulsivity/user_requested/risk_circuit_breaker
    affected_scope: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    recovery_conditions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")  # active/resolved/expired
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)  # user_confirmation/review_completion/expiry
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
