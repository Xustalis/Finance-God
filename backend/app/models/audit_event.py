"""审计事件表"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Integer, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_subject", "subject_type", "subject_id"),
        Index("ix_audit_correlation", "request_correlation_id"),
        Index("ix_audit_user_time", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)
    subject_type: Mapped[str] = mapped_column(String(64), nullable=False)  # profile/mandate/strategy/portfolio/order/risk_event
    subject_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    before_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    after_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_correlation_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    actor: Mapped[str] = mapped_column(String(64), nullable=False, default="system")  # user/system/agent_name
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
