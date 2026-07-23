"""目标组合表"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import String, DateTime, Integer, Boolean, Text, Numeric
from sqlalchemy.dialects.postgresql import UUID, JSONB, NUMERIC
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TargetPortfolio(Base):
    __tablename__ = "target_portfolios"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)
    strategy_proposal_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    mandate_version: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    holding_snapshot_version: Mapped[int] = mapped_column(Integer, nullable=False)
    market_context_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    target_weights: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    constraint_report: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    risk_metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    rebalance_plan: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    total_expected_cost: Mapped[Decimal] = mapped_column(NUMERIC(18, 4), nullable=False, default=Decimal("0"))
    total_expected_slippage: Mapped[Decimal] = mapped_column(NUMERIC(18, 4), nullable=False, default=Decimal("0"))
    constructible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    constructible_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_coverage: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("1"))
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")  # draft/confirmed/executing/executed/invalid
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
