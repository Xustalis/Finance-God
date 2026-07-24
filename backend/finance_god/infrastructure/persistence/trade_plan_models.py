from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base, UTCDateTime


class TradePlanVersionRow(Base):
    """Append-only persisted TradePlan version."""

    __tablename__ = "trade_plan_versions"
    __table_args__ = (
        CheckConstraint("revision >= 1", name="ck_trade_plan_revision_positive"),
        UniqueConstraint(
            "owner_user_id",
            "creation_key",
            name="uq_trade_plan_owner_creation_key",
        ),
        Index("ix_trade_plan_versions_owner", "owner_user_id"),
        Index("ix_trade_plan_versions_status", "status"),
    )

    plan_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(160), nullable=False)
    account_id: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[str] = mapped_column(String(160), nullable=False)
    creation_key: Mapped[str | None] = mapped_column(String(200))
    plan_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    data_status_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class TradePlanDraftLinkRow(Base):
    __tablename__ = "trade_plan_draft_links"
    __table_args__ = (
        UniqueConstraint(
            "plan_id",
            "plan_revision",
            "action_id",
            name="uq_trade_plan_draft_action",
        ),
        UniqueConstraint("draft_id", name="uq_trade_plan_draft_id"),
        Index("ix_trade_plan_draft_links_plan", "plan_id", "plan_revision"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_id: Mapped[str] = mapped_column(String(160), nullable=False)
    plan_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    action_id: Mapped[str] = mapped_column(String(160), nullable=False)
    draft_id: Mapped[str] = mapped_column(String(160), nullable=False)
    draft_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
