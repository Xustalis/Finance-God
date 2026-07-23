"""仿真账户表"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import String, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB, NUMERIC
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SimulatedAccount(Base):
    __tablename__ = "simulated_accounts"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), unique=True, nullable=False, index=True)
    cash_balance: Mapped[Decimal] = mapped_column(NUMERIC(18, 4), nullable=False, default=Decimal("1000000"))
    total_market_value: Mapped[Decimal] = mapped_column(NUMERIC(18, 4), nullable=False, default=Decimal("0"))
    total_value: Mapped[Decimal] = mapped_column(NUMERIC(18, 4), nullable=False, default=Decimal("1000000"))
    positions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    total_fee_paid: Mapped[Decimal] = mapped_column(NUMERIC(18, 4), nullable=False, default=Decimal("0"))
    total_slippage: Mapped[Decimal] = mapped_column(NUMERIC(18, 4), nullable=False, default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")  # active/paused/closed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
