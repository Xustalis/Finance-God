"""市场环境快照表"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import String, DateTime, Integer, Numeric
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MarketContext(Base):
    __tablename__ = "market_contexts"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    markets: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    overall_sentiment: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0.5"))
    events_summary: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    data_quality: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    sources: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    applicable_markets: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    applicable_instruments: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0"))
    usable_status: Mapped[str] = mapped_column(String(32), nullable=False, default="usable")  # usable/stale/conflicting/insufficient
    data_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
