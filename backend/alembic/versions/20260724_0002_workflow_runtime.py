"""Create the durable workflow runtime and append-only workflow facts.

Revision ID: 20260724_0002
Revises: 20260723_0001
Create Date: 2026-07-24
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# Register these explicit migration tables on Alembic's shared target metadata.
# The migration definitions below remain self-contained and immutable.
from finance_god.infrastructure.persistence import (  # noqa: F401
    workflow_models as _workflow_models,
)

revision = "20260724_0005_finance_workflow"
down_revision = "20260724_0004_finance_ledger"
branch_labels = None
depends_on = None

UTC = sa.DateTime(timezone=True)
WORKFLOW_FACT_TABLES = (
    "workflow_events",
    "workflow_audit_records",
    "workflow_execution_audit_records",
)
WORKFLOW_STATUSES = (
    "'queued'",
    "'running'",
    "'completed'",
    "'attention_required'",
    "'failed'",
    "'timed_out'",
    "'blocked'",
    "'expired'",
    "'cancel_requested'",
    "'cancelling'",
    "'cancelled'",
)


def upgrade() -> None:
    _create_workflow_runs()
    _create_workflow_events()
    _create_workflow_audit_records()
    _create_workflow_execution_audit_records()
    _create_workflow_outbox_messages()
    _create_fact_guards()


def downgrade() -> None:
    dialect = op.get_context().dialect.name
    if dialect == "sqlite":
        for table in WORKFLOW_FACT_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_update")
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_delete")
    elif dialect == "postgresql":
        for table in WORKFLOW_FACT_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_mutation ON {table}")
    op.drop_table("workflow_outbox_messages")
    op.drop_table("workflow_execution_audit_records")
    op.drop_table("workflow_audit_records")
    op.drop_table("workflow_events")
    op.drop_table("workflow_runs")
    if dialect == "postgresql":
        op.execute(
            "DROP FUNCTION IF EXISTS finance_god_prevent_workflow_fact_mutation()"
        )


def _create_workflow_runs() -> None:
    status_sql = ",".join(WORKFLOW_STATUSES)
    op.create_table(
        "workflow_runs",
        sa.Column("run_id", sa.String(160), primary_key=True),
        sa.Column("stable_trigger_key", sa.String(160), nullable=False, unique=True),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("request_intent", sa.String(500), nullable=False),
        sa.Column("owner_id", sa.String(160), nullable=False),
        sa.Column("scope", sa.String(2000), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("workflow_key", sa.String(80), nullable=False),
        sa.Column("workflow_version", sa.String(80), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("trade_eligible", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("state_json", sa.JSON(), nullable=False),
        sa.Column("requested_at", UTC, nullable=False),
        sa.Column("created_at", UTC, nullable=False),
        sa.Column("updated_at", UTC, nullable=False),
        sa.UniqueConstraint(
            "owner_id",
            "idempotency_key",
            name="uq_workflow_run_owner_idempotency",
        ),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_workflow_run_revision_positive",
        ),
        sa.CheckConstraint(
            f"status IN ({status_sql})",
            name="ck_workflow_run_status",
        ),
        sa.CheckConstraint(
            "trade_eligible = false OR status = 'completed'",
            name="ck_workflow_run_trade_eligible",
        ),
        sa.CheckConstraint(
            "length(request_hash) = 64",
            name="ck_workflow_run_request_hash",
        ),
    )
    op.create_index(
        "ix_workflow_runs_workflow_key",
        "workflow_runs",
        ["workflow_key"],
    )
    op.create_index(
        "ix_workflow_runs_status",
        "workflow_runs",
        ["status"],
    )


def _create_workflow_events() -> None:
    op.create_table(
        "workflow_events",
        sa.Column("event_id", sa.String(160), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(160),
            sa.ForeignKey("workflow_runs.run_id"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(48), nullable=False),
        sa.Column("prior_status", sa.String(32)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("audit_id", sa.String(160), nullable=False, unique=True),
        sa.Column("actor_id", sa.String(160), nullable=False),
        sa.Column("correlation_id", sa.String(160), nullable=False),
        sa.Column("causation_id", sa.String(160), nullable=False),
        sa.Column("previous_event_hash", sa.String(64)),
        sa.Column("event_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("occurred_at", UTC, nullable=False),
        sa.Column("state_json", sa.JSON(), nullable=False),
        sa.UniqueConstraint(
            "run_id",
            "sequence",
            name="uq_workflow_event_run_sequence",
        ),
        sa.UniqueConstraint(
            "run_id",
            "revision",
            name="uq_workflow_event_run_revision",
        ),
        sa.CheckConstraint(
            "sequence >= 1",
            name="ck_workflow_event_sequence",
        ),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_workflow_event_revision",
        ),
        sa.CheckConstraint(
            "length(event_hash) = 64",
            name="ck_workflow_event_hash",
        ),
        sa.CheckConstraint(
            "previous_event_hash IS NULL OR length(previous_event_hash) = 64",
            name="ck_workflow_previous_event_hash",
        ),
    )
    op.create_index(
        "ix_workflow_events_run_id",
        "workflow_events",
        ["run_id"],
    )


def _create_workflow_audit_records() -> None:
    op.create_table(
        "workflow_audit_records",
        sa.Column("audit_id", sa.String(160), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(160),
            sa.ForeignKey("workflow_runs.run_id"),
            nullable=False,
        ),
        sa.Column(
            "event_id",
            sa.String(160),
            sa.ForeignKey("workflow_events.event_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("actor_id", sa.String(160), nullable=False),
        sa.Column("correlation_id", sa.String(160), nullable=False),
        sa.Column("state_hash", sa.String(64), nullable=False),
        sa.Column("event_hash", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("occurred_at", UTC, nullable=False),
        sa.UniqueConstraint(
            "run_id",
            "revision",
            name="uq_workflow_audit_run_revision",
        ),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_workflow_audit_revision",
        ),
        sa.CheckConstraint(
            "length(state_hash) = 64",
            name="ck_workflow_audit_state_hash",
        ),
        sa.CheckConstraint(
            "length(event_hash) = 64",
            name="ck_workflow_audit_event_hash",
        ),
    )
    op.create_index(
        "ix_workflow_audit_records_run_id",
        "workflow_audit_records",
        ["run_id"],
    )


def _create_workflow_outbox_messages() -> None:
    op.create_table(
        "workflow_outbox_messages",
        sa.Column("message_id", sa.String(160), primary_key=True),
        sa.Column("topic", sa.String(160), nullable=False),
        sa.Column(
            "aggregate_id",
            sa.String(160),
            sa.ForeignKey("workflow_runs.run_id"),
            nullable=False,
        ),
        sa.Column(
            "event_id",
            sa.String(160),
            sa.ForeignKey("workflow_events.event_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("event_hash", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("occurred_at", UTC, nullable=False),
        sa.Column("published_at", UTC),
        sa.CheckConstraint(
            "length(event_hash) = 64",
            name="ck_workflow_outbox_event_hash",
        ),
    )
    op.create_index(
        "ix_workflow_outbox_unpublished",
        "workflow_outbox_messages",
        ["published_at"],
    )


def _create_workflow_execution_audit_records() -> None:
    op.create_table(
        "workflow_execution_audit_records",
        sa.Column("audit_id", sa.String(160), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(160),
            sa.ForeignKey("workflow_runs.run_id"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("actor_id", sa.String(160)),
        sa.Column("correlation_id", sa.String(160)),
        sa.Column("occurred_at", UTC, nullable=False),
    )
    op.create_index(
        "ix_workflow_execution_audit_run_id",
        "workflow_execution_audit_records",
        ["run_id"],
    )
    op.create_index(
        "ix_workflow_execution_audit_occurred_at",
        "workflow_execution_audit_records",
        ["occurred_at"],
    )


def _create_fact_guards() -> None:
    dialect = op.get_context().dialect.name
    if dialect == "sqlite":
        for table in WORKFLOW_FACT_TABLES:
            op.execute(
                f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} "
                "BEGIN SELECT RAISE(ABORT, 'append-only workflow fact table'); END"
            )
            op.execute(
                f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} "
                "BEGIN SELECT RAISE(ABORT, 'append-only workflow fact table'); END"
            )
    elif dialect == "postgresql":
        op.execute(
            "CREATE OR REPLACE FUNCTION "
            "finance_god_prevent_workflow_fact_mutation() "
            "RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
            "RAISE EXCEPTION 'append-only workflow fact table'; END $$"
        )
        for table in WORKFLOW_FACT_TABLES:
            op.execute(
                f"CREATE TRIGGER {table}_no_mutation "
                f"BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW "
                "EXECUTE FUNCTION finance_god_prevent_workflow_fact_mutation()"
            )
