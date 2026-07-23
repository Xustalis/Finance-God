"""研究备忘录表"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ResearchMemo(Base):
    __tablename__ = "research_memos"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    instrument_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    evidence: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    facts: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    inferences: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    bull_case: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    bear_case: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    base_case: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    risks: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    unknowns: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="in_progress")  # in_progress/usable/insufficient/expired/superseded
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
