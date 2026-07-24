from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, cast

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DDL,
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


_WORKFLOW_STATUSES = (
    "queued",
    "running",
    "completed",
    "attention_required",
    "failed",
    "timed_out",
    "blocked",
    "expired",
    "cancel_requested",
    "cancelling",
    "cancelled",
)
_STATUS_SQL = ",".join(f"'{status}'" for status in _WORKFLOW_STATUSES)


class WorkflowRunRow(Base):
    """Current, CAS-protected projection of a workflow aggregate."""

    __tablename__ = "workflow_runs"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "idempotency_key",
            name="uq_workflow_run_owner_idempotency",
        ),
        CheckConstraint("revision >= 1", name="ck_workflow_run_revision_positive"),
        CheckConstraint(
            f"status IN ({_STATUS_SQL})",
            name="ck_workflow_run_status",
        ),
        CheckConstraint(
            "trade_eligible = false OR status = 'completed'",
            name="ck_workflow_run_trade_eligible",
        ),
        CheckConstraint(
            "length(request_hash) = 64",
            name="ck_workflow_run_request_hash",
        ),
        Index("ix_workflow_runs_workflow_key", "workflow_key"),
        Index("ix_workflow_runs_status", "status"),
    )

    run_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    stable_trigger_key: Mapped[str] = mapped_column(
        String(160), nullable=False, unique=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    request_intent: Mapped[str] = mapped_column(String(500), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(160), nullable=False)
    scope: Mapped[str] = mapped_column(String(2_000), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    workflow_key: Mapped[str] = mapped_column(String(80), nullable=False)
    workflow_version: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    trade_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    state_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class WorkflowEventRow(Base):
    """Append-only workflow state event with a per-run hash chain."""

    __tablename__ = "workflow_events"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "sequence",
            name="uq_workflow_event_run_sequence",
        ),
        UniqueConstraint(
            "run_id",
            "revision",
            name="uq_workflow_event_run_revision",
        ),
        CheckConstraint("sequence >= 1", name="ck_workflow_event_sequence"),
        CheckConstraint("revision >= 1", name="ck_workflow_event_revision"),
        CheckConstraint(
            "length(event_hash) = 64",
            name="ck_workflow_event_hash",
        ),
        CheckConstraint(
            "previous_event_hash IS NULL OR length(previous_event_hash) = 64",
            name="ck_workflow_previous_event_hash",
        ),
        Index("ix_workflow_events_run_id", "run_id"),
    )

    event_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_runs.run_id"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    prior_status: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    audit_id: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    actor_id: Mapped[str] = mapped_column(String(160), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(160), nullable=False)
    causation_id: Mapped[str] = mapped_column(String(160), nullable=False)
    previous_event_hash: Mapped[str | None] = mapped_column(String(64))
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    state_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class WorkflowAuditRow(Base):
    """Append-only, queryable audit anchor for every persisted revision."""

    __tablename__ = "workflow_audit_records"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "revision",
            name="uq_workflow_audit_run_revision",
        ),
        CheckConstraint("revision >= 1", name="ck_workflow_audit_revision"),
        CheckConstraint(
            "length(state_hash) = 64",
            name="ck_workflow_audit_state_hash",
        ),
        CheckConstraint(
            "length(event_hash) = 64",
            name="ck_workflow_audit_event_hash",
        ),
        Index("ix_workflow_audit_records_run_id", "run_id"),
    )

    audit_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_runs.run_id"), nullable=False
    )
    event_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_events.event_id"), nullable=False, unique=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(160), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(160), nullable=False)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class WorkflowOutboxRow(Base):
    """Transactional outbox record; publication may mark published_at later."""

    __tablename__ = "workflow_outbox_messages"
    __table_args__ = (
        CheckConstraint(
            "length(event_hash) = 64",
            name="ck_workflow_outbox_event_hash",
        ),
        Index("ix_workflow_outbox_unpublished", "published_at"),
    )

    message_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    topic: Mapped[str] = mapped_column(String(160), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_runs.run_id"), nullable=False
    )
    event_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_events.event_id"), nullable=False, unique=True
    )
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class WorkflowExecutionAuditRow(Base):
    """Append-only operational audit that does not advance aggregate revision."""

    __tablename__ = "workflow_execution_audit_records"
    __table_args__ = (
        Index("ix_workflow_execution_audit_run_id", "run_id"),
        Index("ix_workflow_execution_audit_occurred_at", "occurred_at"),
    )

    audit_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_runs.run_id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(160))
    correlation_id: Mapped[str | None] = mapped_column(String(160))
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


WORKFLOW_FACT_TABLES: tuple[Table, ...] = (
    cast(Table, WorkflowEventRow.__table__),
    cast(Table, WorkflowAuditRow.__table__),
    cast(Table, WorkflowExecutionAuditRow.__table__),
)
typed_ddl = cast(Callable[[str], DDL], DDL)


for fact_table in WORKFLOW_FACT_TABLES:
    event.listen(
        fact_table,
        "after_create",
        typed_ddl(
            f"CREATE TRIGGER {fact_table.name}_no_update "
            f"BEFORE UPDATE ON {fact_table.name} "
            "BEGIN SELECT RAISE(ABORT, 'append-only workflow fact table'); END"
        ).execute_if(dialect="sqlite"),
    )
    event.listen(
        fact_table,
        "after_create",
        typed_ddl(
            f"CREATE TRIGGER {fact_table.name}_no_delete "
            f"BEFORE DELETE ON {fact_table.name} "
            "BEGIN SELECT RAISE(ABORT, 'append-only workflow fact table'); END"
        ).execute_if(dialect="sqlite"),
    )
    event.listen(
        fact_table,
        "after_create",
        typed_ddl(
            f"CREATE TRIGGER {fact_table.name}_no_mutation "
            f"BEFORE UPDATE OR DELETE ON {fact_table.name} "
            "FOR EACH ROW EXECUTE FUNCTION finance_god_prevent_workflow_fact_mutation()"
        ).execute_if(dialect="postgresql"),
    )


event.listen(
    Base.metadata,
    "before_create",
    typed_ddl(
        "CREATE OR REPLACE FUNCTION finance_god_prevent_workflow_fact_mutation() "
        "RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
        "RAISE EXCEPTION 'append-only workflow fact table'; END $$"
    ).execute_if(dialect="postgresql"),
)
