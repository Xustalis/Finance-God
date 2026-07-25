from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base, UTCDateTime

_PRICE = Numeric(28, 8, asdecimal=True)
_RATE = Numeric(28, 12, asdecimal=True)


class MarketSnapshotRow(Base):
    """Latest server-polled snapshot per instrument (anomaly-detection baseline)."""

    __tablename__ = "market_snapshots"

    symbol: Mapped[str] = mapped_column(String(160), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    last: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    change_percent: Mapped[Decimal | None] = mapped_column(_RATE)
    provider_time: Mapped[str] = mapped_column(String(80), nullable=False)
    frequency: Mapped[str] = mapped_column(String(40), nullable=False)
    freshness: Mapped[str] = mapped_column(String(40), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class MarketAlertRow(Base):
    """Append-only, global record of a significant market move for review."""

    __tablename__ = "market_alerts"
    __table_args__ = (
        UniqueConstraint("alert_id", name="uq_market_alert_id"),
        Index("ix_market_alerts_detected_at", "detected_at"),
        Index("ix_market_alerts_symbol", "symbol"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alert_id: Mapped[str] = mapped_column(String(160), nullable=False)
    symbol: Mapped[str] = mapped_column(String(160), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    change_percent: Mapped[Decimal] = mapped_column(_RATE, nullable=False)
    last: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    message: Mapped[str] = mapped_column(String(1000), nullable=False)
    provider_time: Mapped[str] = mapped_column(String(80), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class MarketAlertDispatchRow(Base):
    """Durable outbox entry; user projection retries independently of ingestion."""

    __tablename__ = "market_alert_dispatch_outbox"

    alert_id: Mapped[str] = mapped_column(
        ForeignKey("market_alerts.alert_id"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    dispatched_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(String(500))
