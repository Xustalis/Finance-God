"""资产主数据表"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import String, DateTime, Index, Numeric
from sqlalchemy.dialects.postgresql import UUID, JSONB, NUMERIC
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Instrument(Base):
    __tablename__ = "instruments"
    __table_args__ = (
        Index("ix_instrument_market_type", "market", "asset_type", "status"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    symbol: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(32), nullable=False)  # etf/mutual_fund
    market: Mapped[str] = mapped_column(String(32), nullable=False)  # a_shares/us_stocks/hk_stocks
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    exchange: Mapped[str | None] = mapped_column(String(32), nullable=True)
    min_trade_unit: Mapped[Decimal] = mapped_column(NUMERIC(18, 4), nullable=False, default=Decimal("1"))
    expense_ratio: Mapped[Decimal | None] = mapped_column(Numeric(8, 6), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(100), nullable=True)
    benchmark: Mapped[str | None] = mapped_column(String(100), nullable=True)
    trading_attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    available_regions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")  # active/suspended/delisted
    data_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
