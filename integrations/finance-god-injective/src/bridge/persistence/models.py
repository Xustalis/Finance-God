from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

PLAN_STATUSES = (
    "draft",
    "reviewed",
    "confirmed",
    "submitted",
    "rejected",
    "expired",
    "submission_failed",
)
ORDER_STATUSES = (
    "broadcasting",
    "broadcast",
    "open",
    "partially_filled",
    "filled",
    "cancelled",
    "rejected",
    "unknown",
)
BROADCAST_ATTEMPT_STATUSES = ("started", "broadcast", "failed", "unknown")
IDEMPOTENCY_STATUSES = ("in_progress", "completed", "failed")
ACTIVE_ORDER_STATUSES = (
    "broadcasting",
    "broadcast",
    "open",
    "partially_filled",
    "unknown",
)

DECIMAL_TYPE = Numeric(50, 18)


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid4())


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class SourceSnapshotModel(Base):
    __tablename__ = "source_snapshots"
    __table_args__ = (
        CheckConstraint(
            "classification = 'context_only'",
            name="source_snapshot_context_only",
        ),
        CheckConstraint(
            "asset_domain = 'non_executable_asset_domain'",
            name="source_snapshot_non_executable",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_plan_id: Mapped[str] = mapped_column(String(160), index=True)
    source_draft_id: Mapped[str | None] = mapped_column(String(160))
    source_plan_version: Mapped[str | None] = mapped_column(String(80))
    source_plan_status: Mapped[str | None] = mapped_column(String(80))
    source_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    audit_reference: Mapped[str | None] = mapped_column(String(255))
    draft_status: Mapped[str | None] = mapped_column(String(80))
    draft_confirmed: Mapped[bool | None] = mapped_column(Boolean)
    classification: Mapped[str] = mapped_column(String(32), default="context_only")
    asset_domain: Mapped[str] = mapped_column(
        String(64),
        default="non_executable_asset_domain",
    )
    normalized_hash: Mapped[str] = mapped_column(String(64), unique=True)
    projection: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
    )


class InjectivePlanModel(Base):
    __tablename__ = "injective_plans"
    __table_args__ = (
        CheckConstraint("side IN ('buy', 'sell')", name="injective_plan_side"),
        CheckConstraint("order_type = 'limit'", name="injective_plan_limit_only"),
        CheckConstraint("time_in_force = 'gtc'", name="injective_plan_gtc_only"),
        CheckConstraint("price > 0", name="injective_plan_price_positive"),
        CheckConstraint("quantity > 0", name="injective_plan_quantity_positive"),
        CheckConstraint("revision >= 1", name="injective_plan_revision_positive"),
        CheckConstraint(
            f"status IN ({_quoted(PLAN_STATUSES)})",
            name="injective_plan_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    market_id: Mapped[str] = mapped_column(String(80), index=True)
    ticker: Mapped[str] = mapped_column(String(40))
    source_snapshot_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("source_snapshots.id", ondelete="RESTRICT"),
        index=True,
    )
    side: Mapped[str] = mapped_column(String(4))
    order_type: Mapped[str] = mapped_column(String(16), default="limit")
    time_in_force: Mapped[str] = mapped_column(String(16), default="gtc")
    price: Mapped[Decimal] = mapped_column(DECIMAL_TYPE)
    quantity: Mapped[Decimal] = mapped_column(DECIMAL_TYPE)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    risk_report: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        onupdate=utc_now,
    )


class InjectiveOrderModel(Base):
    __tablename__ = "injective_orders"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_quoted(ORDER_STATUSES)})",
            name="injective_order_status",
        ),
        CheckConstraint(
            "filled_quantity >= 0",
            name="injective_order_filled_quantity_nonnegative",
        ),
        CheckConstraint(
            "filled_quantity <= quantity",
            name="injective_order_filled_quantity_lte_quantity",
        ),
        CheckConstraint("quantity > 0", name="injective_order_quantity_positive"),
        CheckConstraint("revision >= 1", name="injective_order_revision_positive"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    plan_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("injective_plans.id", ondelete="RESTRICT"),
        unique=True,
    )
    market_id: Mapped[str] = mapped_column(String(80), index=True)
    subaccount_id: Mapped[str] = mapped_column(String(80), index=True)
    client_order_id: Mapped[str] = mapped_column(String(80), unique=True)
    status: Mapped[str] = mapped_column(String(32), default="broadcasting", index=True)
    tx_hash: Mapped[str | None] = mapped_column(String(128), unique=True)
    order_hash: Mapped[str | None] = mapped_column(String(128), unique=True)
    quantity: Mapped[Decimal] = mapped_column(DECIMAL_TYPE)
    filled_quantity: Mapped[Decimal] = mapped_column(
        DECIMAL_TYPE,
        default=Decimal("0"),
    )
    revision: Mapped[int] = mapped_column(Integer, default=1)
    chain_projection: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    last_chain_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        onupdate=utc_now,
    )


class OrderEventModel(Base):
    __tablename__ = "order_events"
    __table_args__ = (
        UniqueConstraint(
            "event_key",
            "payload_hash",
            name="uq_order_event_source_payload",
        ),
        CheckConstraint(
            f"status IN ({_quoted(ORDER_STATUSES)})",
            name="order_event_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    order_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("injective_orders.id", ondelete="CASCADE"),
        index=True,
    )
    event_key: Mapped[str] = mapped_column(String(255))
    payload_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
    )


class BroadcastAttemptModel(Base):
    __tablename__ = "broadcast_attempts"
    __table_args__ = (
        UniqueConstraint("order_id", "attempt_no", name="uq_broadcast_order_attempt"),
        CheckConstraint(
            f"status IN ({_quoted(BROADCAST_ATTEMPT_STATUSES)})",
            name="broadcast_attempt_status",
        ),
        CheckConstraint("attempt_no >= 1", name="broadcast_attempt_number_positive"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    plan_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("injective_plans.id", ondelete="RESTRICT"),
        index=True,
    )
    order_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("injective_orders.id", ondelete="CASCADE"),
        index=True,
    )
    attempt_no: Mapped[int] = mapped_column(Integer)
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="started")
    tx_hash: Mapped[str | None] = mapped_column(String(128))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IdempotencyRecordModel(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("operation", "idempotency_key", name="uq_idempotency_operation_key"),
        CheckConstraint(
            f"status IN ({_quoted(IDEMPOTENCY_STATUSES)})",
            name="idempotency_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    operation: Mapped[str] = mapped_column(String(120))
    idempotency_key: Mapped[str] = mapped_column(String(255))
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="in_progress")
    response_code: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    resource_type: Mapped[str | None] = mapped_column(String(80))
    resource_id: Mapped[str | None] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        onupdate=utc_now,
    )


Index(
    "ix_injective_orders_subaccount_status",
    InjectiveOrderModel.subaccount_id,
    InjectiveOrderModel.status,
)
