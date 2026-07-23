"""持仓快照表"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import String, DateTime, Integer, Numeric, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB, NUMERIC
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class HoldingSnapshot(Base):
    __tablename__ = "holding_snapshots"
    __table_args__ = (UniqueConstraint("user_id", "version", name="uq_holding_user_version"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")  # manual/csv_import/broker_sync
    positions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    unresolved_positions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    unresolved_weight: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0"))
    total_market_value: Mapped[Decimal] = mapped_column(NUMERIC(18, 4), nullable=False, default=Decimal("0"))
    total_cost_basis: Mapped[Decimal] = mapped_column(NUMERIC(18, 4), nullable=False, default=Decimal("0"))
    cash_balance: Mapped[Decimal] = mapped_column(NUMERIC(18, 4), nullable=False, default=Decimal("0"))
    valuation_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
