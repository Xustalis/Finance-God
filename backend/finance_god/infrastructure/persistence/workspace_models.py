from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base, UTCDateTime


class WatchlistGroupRow(Base):
    __tablename__ = "watchlist_groups"
    __table_args__ = (
        CheckConstraint("revision >= 1", name="ck_watchlist_group_revision_positive"),
        Index("ix_watchlist_groups_owner_id", "owner_user_id"),
    )

    group_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(160), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class WatchlistInstrumentRow(Base):
    __tablename__ = "watchlist_instruments"
    __table_args__ = (
        UniqueConstraint(
            "group_id", "instrument_id", name="uq_watchlist_instrument_group_instrument"
        ),
        CheckConstraint("revision >= 1", name="ck_watchlist_instrument_revision_positive"),
        Index("ix_watchlist_instruments_group_id", "group_id"),
        Index("ix_watchlist_instruments_instrument_id", "instrument_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[str] = mapped_column(
        ForeignKey("watchlist_groups.group_id"), nullable=False
    )
    instrument_id: Mapped[str] = mapped_column(String(160), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    added_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    added_by: Mapped[str] = mapped_column(String(160), nullable=False)


class CandidateIgnoreRow(Base):
    __tablename__ = "candidate_ignores"
    __table_args__ = (
        UniqueConstraint(
            "owner_user_id",
            "instrument_id",
            name="uq_candidate_ignore_owner_instrument",
        ),
        CheckConstraint("revision >= 1", name="ck_candidate_ignore_revision_positive"),
        Index("ix_candidate_ignores_owner_id", "owner_user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_user_id: Mapped[str] = mapped_column(String(160), nullable=False)
    instrument_id: Mapped[str] = mapped_column(String(160), nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500))
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class NotificationRow(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint(
            "notification_id != 'system:required'", name="ck_notification_id_not_system"
        ),
        Index("ix_notifications_owner_id", "owner_user_id"),
        Index("ix_notifications_status", "status"),
        Index("ix_notifications_category", "category"),
        Index("ix_notifications_severity", "severity"),
        UniqueConstraint(
            "owner_user_id",
            "source_object_type",
            "source_object_id",
            name="uq_notifications_owner_source",
        ),
    )

    notification_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(String(1000), nullable=False)
    details_json: Mapped[dict[str, str]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    source_object_type: Mapped[str] = mapped_column(String(80), nullable=False)
    source_object_id: Mapped[str] = mapped_column(String(160), nullable=False)
    source_version: Mapped[str] = mapped_column(String(80), nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    audit_id: Mapped[str] = mapped_column(String(160), nullable=False)
    audit_actor_id: Mapped[str] = mapped_column(String(160), nullable=False)
    audit_recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class NotificationReceiptRow(Base):
    __tablename__ = "notification_receipts"
    __table_args__ = (
        UniqueConstraint("notification_id", name="uq_receipt_notification"),
        Index("ix_notification_receipts_owner_id", "owner_user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    notification_id: Mapped[str] = mapped_column(
        ForeignKey("notifications.notification_id"), nullable=False
    )
    owner_user_id: Mapped[str] = mapped_column(String(160), nullable=False)
    read_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)


class NotificationPreferenceRow(Base):
    __tablename__ = "notification_preferences"

    owner_user_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    preferences_json: Mapped[dict[str, bool]] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class UserMarketFocusRow(Base):
    __tablename__ = "user_market_focus"

    owner_user_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class UserEventRow(Base):
    __tablename__ = "user_events"
    __table_args__ = (
        UniqueConstraint(
            "owner_user_id",
            "event_id",
            name="uq_user_events_owner_event",
        ),
        Index("ix_user_events_owner_cursor", "owner_user_id", "cursor"),
    )

    cursor: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(160), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(160), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    notification_id: Mapped[str] = mapped_column(
        ForeignKey("notifications.notification_id"), nullable=False
    )
    fact_version: Mapped[str] = mapped_column(String(160), nullable=False)
    payload_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class NotificationDeliveryRow(Base):
    __tablename__ = "notification_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "notification_id",
            "channel",
            name="uq_notification_delivery_channel",
        ),
        Index("ix_notification_deliveries_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    notification_id: Mapped[str] = mapped_column(
        ForeignKey("notifications.notification_id"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    error: Mapped[str | None] = mapped_column(String(500))
