"""订单意图表"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import String, DateTime, Integer, Text, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB, NUMERIC
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class OrderIntent(Base):
    __tablename__ = "order_intents"
    __table_args__ = (
        Index("ix_order_user_status", "user_id", "status"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)
    account_type: Mapped[str] = mapped_column(String(32), nullable=False, default="simulation")  # simulation/live
    instrument_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)  # buy/sell
    quantity: Mapped[Decimal] = mapped_column(NUMERIC(18, 4), nullable=False)
    price_limit: Mapped[Decimal | None] = mapped_column(NUMERIC(18, 4), nullable=True)
    price_protection: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    mandate_version: Mapped[int] = mapped_column(Integer, nullable=False)
    portfolio_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    strategy_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    risk_check_1: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    risk_check_2: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    risk_check_3: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")  # pending/approved/queued/submitted/partial_fill/filled/blocked/rejected/cancelled
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    blocked_by: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
