"""策略方案表"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class StrategyProposal(Base):
    __tablename__ = "strategy_proposals"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)
    mandate_version: Mapped[int] = mapped_column(Integer, nullable=False)
    market_context_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    research_memo_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    global_allocation: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    market_allocation: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    mental_adaptations: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    risk_scenarios: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    assumptions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    applicable_mandate_scope: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    invalidation_conditions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    explanation: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="candidate")  # candidate/accepted/rejected/superseded/invalid
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
