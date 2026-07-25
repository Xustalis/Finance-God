from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base, UTCDateTime


class TradeEpisodeRow(Base):
    __tablename__ = "trade_episodes"
    __table_args__ = (
        CheckConstraint("revision >= 1", name="ck_trade_episode_revision"),
        Index(
            "uq_trade_episode_open",
            "owner_id",
            "account_id",
            "instrument_id",
            unique=True,
            sqlite_where=__import__("sqlalchemy").text("status = 'open'"),
            postgresql_where=__import__("sqlalchemy").text("status = 'open'"),
        ),
        Index("ix_trade_episode_owner_updated", "owner_id", "updated_at"),
    )

    episode_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(160), nullable=False)
    account_id: Mapped[str] = mapped_column(String(160), nullable=False)
    instrument_id: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    review_status: Mapped[str | None] = mapped_column(String(24))
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    opened_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class TradeDecisionSnapshotRow(Base):
    __tablename__ = "trade_decision_snapshots"
    __table_args__ = (
        Index("ix_trade_decision_episode_time", "episode_id", "occurred_at"),
    )

    snapshot_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    episode_id: Mapped[str] = mapped_column(
        ForeignKey("trade_episodes.episode_id"), nullable=False
    )
    owner_id: Mapped[str] = mapped_column(String(160), nullable=False)
    order_id: Mapped[str] = mapped_column(String(160), nullable=False)
    fill_id: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class TradeReviewRow(Base):
    __tablename__ = "trade_reviews"
    __table_args__ = (
        UniqueConstraint("episode_id", "kind", name="uq_trade_review_episode_kind"),
        Index("ix_trade_review_owner_status", "owner_id", "status"),
    )

    review_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    episode_id: Mapped[str] = mapped_column(
        ForeignKey("trade_episodes.episode_id"), nullable=False
    )
    owner_id: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ProfileFeedbackRow(Base):
    __tablename__ = "trade_profile_feedback"

    feedback_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(160), nullable=False)
    episode_id: Mapped[str] = mapped_column(
        ForeignKey("trade_episodes.episode_id"), nullable=False
    )
    review_id: Mapped[str] = mapped_column(
        ForeignKey("trade_reviews.review_id"), nullable=False, unique=True
    )
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
