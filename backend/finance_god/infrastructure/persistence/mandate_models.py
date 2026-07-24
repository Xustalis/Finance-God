from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base, UTCDateTime


class InvestmentMandateRow(Base):
    """One immutable authorization version.

    Versions are append-only: ``(owner_user_id, version)`` is unique and the
    current authorization for an owner is the highest version.  Scope lists and
    limits are stored as JSON so the row mirrors the domain model without a wide
    column set.
    """

    __tablename__ = "investment_mandates"
    __table_args__ = (
        UniqueConstraint(
            "owner_user_id", "version", name="uq_investment_mandate_owner_version"
        ),
        CheckConstraint("version >= 1", name="ck_investment_mandate_version_positive"),
        Index("ix_investment_mandates_owner_id", "owner_user_id"),
    )

    mandate_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(160), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    autonomy_level: Mapped[str] = mapped_column(String(8), nullable=False)
    allowed_markets: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    allowed_assets: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    allowed_sides: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    allowed_order_types: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    short_markets: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    limits_json: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    created_by: Mapped[str] = mapped_column(String(160), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500))
