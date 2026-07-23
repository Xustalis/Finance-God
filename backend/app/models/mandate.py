"""投资授权书表"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import String, DateTime, Integer, Text, UniqueConstraint, Index, Numeric
from sqlalchemy.dialects.postgresql import UUID, JSONB, NUMERIC
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class InvestmentMandate(Base):
    __tablename__ = "investment_mandates"
    __table_args__ = (
        UniqueConstraint("user_id", "version", name="uq_mandate_user_version"),
        Index("ix_mandate_user_status", "user_id", "status"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    goal_priorities: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    risk_budget: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    cash_boundary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    asset_scope: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    concentration_limits: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    rebalance_frequency: Mapped[str] = mapped_column(String(32), nullable=False, default="quarterly")
    rebalance_threshold: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0.05"))
    autonomy_level: Mapped[str] = mapped_column(String(4), nullable=False, default="L0")  # L0/L1/L2/L3
    max_single_order_amount: Mapped[Decimal | None] = mapped_column(NUMERIC(18, 4), nullable=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")  # draft/active/paused/revoked/expired/superseded
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
