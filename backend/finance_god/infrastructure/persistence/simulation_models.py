from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, cast

from sqlalchemy import (
    DDL,
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base, UTCDateTime


class SimulationDraftRow(Base):
    __tablename__ = "simulation_order_drafts"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "idempotency_key",
            name="uq_simulation_draft_owner_idempotency",
        ),
        CheckConstraint("revision >= 1", name="ck_simulation_draft_revision"),
        CheckConstraint(
            "length(request_hash) = 64",
            name="ck_simulation_draft_request_hash",
        ),
        Index("ix_simulation_drafts_owner", "owner_id"),
        Index("ix_simulation_drafts_status", "status"),
    )

    draft_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(160), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class SimulationOrderRow(Base):
    __tablename__ = "simulation_execution_orders"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "idempotency_key",
            name="uq_simulation_order_owner_idempotency",
        ),
        UniqueConstraint("draft_id", name="uq_simulation_order_draft"),
        CheckConstraint("revision >= 1", name="ck_simulation_order_revision"),
        CheckConstraint(
            "length(request_hash) = 64",
            name="ck_simulation_order_request_hash",
        ),
        Index("ix_simulation_orders_owner", "owner_id"),
        Index("ix_simulation_orders_status", "status"),
    )

    order_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    draft_id: Mapped[str] = mapped_column(
        ForeignKey("simulation_order_drafts.draft_id"), nullable=False
    )
    owner_id: Mapped[str] = mapped_column(String(160), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    order_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class SimulationExecutionEventRow(Base):
    __tablename__ = "simulation_execution_events"
    __table_args__ = (
        UniqueConstraint(
            "aggregate_type",
            "aggregate_id",
            "sequence",
            name="uq_simulation_event_aggregate_sequence",
        ),
        CheckConstraint("sequence >= 1", name="ck_simulation_event_sequence"),
        CheckConstraint(
            "length(event_hash) = 64",
            name="ck_simulation_event_hash",
        ),
        CheckConstraint(
            "previous_hash IS NULL OR length(previous_hash) = 64",
            name="ck_simulation_event_previous_hash",
        ),
        Index(
            "ix_simulation_events_aggregate",
            "aggregate_type",
            "aggregate_id",
        ),
    )

    event_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    aggregate_type: Mapped[str] = mapped_column(String(24), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(160), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    previous_hash: Mapped[str | None] = mapped_column(String(64))
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class SimulationExecutionAuditRow(Base):
    __tablename__ = "simulation_execution_audit_records"
    __table_args__ = (Index("ix_simulation_audit_aggregate", "aggregate_id"),)

    audit_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    aggregate_id: Mapped[str] = mapped_column(String(160), nullable=False)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("simulation_execution_events.event_id"),
        nullable=False,
        unique=True,
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(160), nullable=False)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class SimulationExecutionOutboxRow(Base):
    __tablename__ = "simulation_execution_outbox"

    message_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("simulation_execution_events.event_id"),
        nullable=False,
        unique=True,
    )
    topic: Mapped[str] = mapped_column(String(160), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(160), nullable=False)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class SimulationFillRow(Base):
    __tablename__ = "simulation_execution_fills"
    __table_args__ = (
        UniqueConstraint("ledger_fill_id", name="uq_simulation_fill_ledger"),
        Index("ix_simulation_fills_order", "order_id"),
    )

    fill_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    order_id: Mapped[str] = mapped_column(
        ForeignKey("simulation_execution_orders.order_id"),
        nullable=False,
    )
    ledger_fill_id: Mapped[str] = mapped_column(String(160), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


SIMULATION_FACT_TABLES: tuple[Table, ...] = (
    cast(Table, SimulationExecutionEventRow.__table__),
    cast(Table, SimulationExecutionAuditRow.__table__),
    cast(Table, SimulationFillRow.__table__),
)
typed_ddl = cast(Callable[[str], DDL], DDL)

for fact_table in SIMULATION_FACT_TABLES:
    event.listen(
        fact_table,
        "after_create",
        typed_ddl(
            f"CREATE TRIGGER {fact_table.name}_no_update "
            f"BEFORE UPDATE ON {fact_table.name} "
            "BEGIN SELECT RAISE(ABORT, 'append-only simulation fact table'); END"
        ).execute_if(dialect="sqlite"),
    )
    event.listen(
        fact_table,
        "after_create",
        typed_ddl(
            f"CREATE TRIGGER {fact_table.name}_no_delete "
            f"BEFORE DELETE ON {fact_table.name} "
            "BEGIN SELECT RAISE(ABORT, 'append-only simulation fact table'); END"
        ).execute_if(dialect="sqlite"),
    )
    event.listen(
        fact_table,
        "after_create",
        typed_ddl(
            f"CREATE TRIGGER {fact_table.name}_no_mutation "
            f"BEFORE UPDATE OR DELETE ON {fact_table.name} "
            "FOR EACH ROW EXECUTE FUNCTION "
            "finance_god_prevent_simulation_fact_mutation()"
        ).execute_if(dialect="postgresql"),
    )

event.listen(
    Base.metadata,
    "before_create",
    typed_ddl(
        "CREATE OR REPLACE FUNCTION finance_god_prevent_simulation_fact_mutation() "
        "RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
        "RAISE EXCEPTION 'append-only simulation fact table'; END $$"
    ).execute_if(dialect="postgresql"),
)
