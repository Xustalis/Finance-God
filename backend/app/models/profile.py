"""量化用户画像表"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import String, DateTime, Integer, Numeric, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class UserProfile(Base):
    __tablename__ = "user_profiles"
    __table_args__ = (UniqueConstraint("user_id", "version", name="uq_profile_user_version"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    goals: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    financial_constraints: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    stated_risk: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    revealed_risk: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    behavioral_prefs: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    restrictions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    completeness: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0"))
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")  # draft/confirmed/superseded
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
