"""执行记录表"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import String, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB, NUMERIC
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ExecutionRecord(Base):
    __tablename__ = "execution_records"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    order_intent_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)
    account_type: Mapped[str] = mapped_column(String(32), nullable=False, default="simulation")
    fills: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    total_filled_quantity: Mapped[Decimal] = mapped_column(NUMERIC(18, 4), nullable=False, default=Decimal("0"))
    total_fee: Mapped[Decimal] = mapped_column(NUMERIC(18, 4), nullable=False, default=Decimal("0"))
    total_slippage: Mapped[Decimal] = mapped_column(NUMERIC(18, 4), nullable=False, default=Decimal("0"))
    avg_fill_price: Mapped[Decimal] = mapped_column(NUMERIC(18, 4), nullable=False, default=Decimal("0"))
    status_history: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    data_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    fee_model: Mapped[str] = mapped_column(String(64), nullable=False, default="flat")
    slippage_model: Mapped[str] = mapped_column(String(64), nullable=False, default="fixed_bps")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
