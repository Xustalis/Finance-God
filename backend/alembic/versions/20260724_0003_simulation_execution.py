"""Create simulation-only draft, order, fill and execution audit storage.

Revision ID: 20260724_0003
Revises: 20260724_0002
Create Date: 2026-07-24
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from finance_god.infrastructure.persistence import (  # noqa: F401
    simulation_models as _simulation_models,
)

revision = "20260724_0006_finance_execution"
down_revision = "20260724_0005_finance_workflow"
branch_labels = None
depends_on = None

UTC = sa.DateTime(timezone=True)
FACT_TABLES = (
    "simulation_execution_events",
    "simulation_execution_audit_records",
    "simulation_execution_fills",
)


def upgrade() -> None:
    _create_drafts()
    _create_orders()
    _create_events()
    _create_audits()
    _create_outbox()
    _create_fills()
    _create_fact_guards()


def downgrade() -> None:
    dialect = op.get_context().dialect.name
    if dialect == "sqlite":
        for table in FACT_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_update")
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_delete")
    elif dialect == "postgresql":
        for table in FACT_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_mutation ON {table}")
    for table in (
        "simulation_execution_fills",
        "simulation_execution_outbox",
        "simulation_execution_audit_records",
        "simulation_execution_events",
        "simulation_execution_orders",
        "simulation_order_drafts",
    ):
        op.drop_table(table)
    if dialect == "postgresql":
        op.execute(
            "DROP FUNCTION IF EXISTS finance_god_prevent_simulation_fact_mutation()"
        )


def _create_drafts() -> None:
    op.create_table(
        "simulation_order_drafts",
        sa.Column("draft_id", sa.String(160), primary_key=True),
        sa.Column("owner_id", sa.String(160), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", UTC, nullable=False),
        sa.Column("updated_at", UTC, nullable=False),
        sa.UniqueConstraint(
            "owner_id",
            "idempotency_key",
            name="uq_simulation_draft_owner_idempotency",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_simulation_draft_revision"),
        sa.CheckConstraint(
            "length(request_hash) = 64",
            name="ck_simulation_draft_request_hash",
        ),
    )
    op.create_index(
        "ix_simulation_drafts_owner",
        "simulation_order_drafts",
        ["owner_id"],
    )
    op.create_index(
        "ix_simulation_drafts_status",
        "simulation_order_drafts",
        ["status"],
    )


def _create_orders() -> None:
    op.create_table(
        "simulation_execution_orders",
        sa.Column("order_id", sa.String(160), primary_key=True),
        sa.Column(
            "draft_id",
            sa.String(160),
            sa.ForeignKey("simulation_order_drafts.draft_id"),
            nullable=False,
        ),
        sa.Column("owner_id", sa.String(160), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("order_kind", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", UTC, nullable=False),
        sa.Column("updated_at", UTC, nullable=False),
        sa.UniqueConstraint(
            "owner_id",
            "idempotency_key",
            name="uq_simulation_order_owner_idempotency",
        ),
        sa.UniqueConstraint("draft_id", name="uq_simulation_order_draft"),
        sa.CheckConstraint("revision >= 1", name="ck_simulation_order_revision"),
        sa.CheckConstraint(
            "length(request_hash) = 64",
            name="ck_simulation_order_request_hash",
        ),
    )
    op.create_index(
        "ix_simulation_orders_owner",
        "simulation_execution_orders",
        ["owner_id"],
    )
    op.create_index(
        "ix_simulation_orders_status",
        "simulation_execution_orders",
        ["status"],
    )


def _create_events() -> None:
    op.create_table(
        "simulation_execution_events",
        sa.Column("event_id", sa.String(160), primary_key=True),
        sa.Column("aggregate_type", sa.String(24), nullable=False),
        sa.Column("aggregate_id", sa.String(160), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("previous_hash", sa.String(64)),
        sa.Column("event_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("occurred_at", UTC, nullable=False),
        sa.UniqueConstraint(
            "aggregate_type",
            "aggregate_id",
            "sequence",
            name="uq_simulation_event_aggregate_sequence",
        ),
        sa.CheckConstraint("sequence >= 1", name="ck_simulation_event_sequence"),
        sa.CheckConstraint(
            "length(event_hash) = 64",
            name="ck_simulation_event_hash",
        ),
        sa.CheckConstraint(
            "previous_hash IS NULL OR length(previous_hash) = 64",
            name="ck_simulation_event_previous_hash",
        ),
    )
    op.create_index(
        "ix_simulation_events_aggregate",
        "simulation_execution_events",
        ["aggregate_type", "aggregate_id"],
    )


def _create_audits() -> None:
    op.create_table(
        "simulation_execution_audit_records",
        sa.Column("audit_id", sa.String(160), primary_key=True),
        sa.Column("aggregate_id", sa.String(160), nullable=False),
        sa.Column(
            "event_id",
            sa.String(160),
            sa.ForeignKey("simulation_execution_events.event_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("actor_id", sa.String(160), nullable=False),
        sa.Column("event_hash", sa.String(64), nullable=False),
        sa.Column("occurred_at", UTC, nullable=False),
    )
    op.create_index(
        "ix_simulation_audit_aggregate",
        "simulation_execution_audit_records",
        ["aggregate_id"],
    )


def _create_outbox() -> None:
    op.create_table(
        "simulation_execution_outbox",
        sa.Column("message_id", sa.String(160), primary_key=True),
        sa.Column(
            "event_id",
            sa.String(160),
            sa.ForeignKey("simulation_execution_events.event_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("topic", sa.String(160), nullable=False),
        sa.Column("aggregate_id", sa.String(160), nullable=False),
        sa.Column("event_hash", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("occurred_at", UTC, nullable=False),
        sa.Column("published_at", UTC),
    )


def _create_fills() -> None:
    op.create_table(
        "simulation_execution_fills",
        sa.Column("fill_id", sa.String(160), primary_key=True),
        sa.Column(
            "order_id",
            sa.String(160),
            sa.ForeignKey("simulation_execution_orders.order_id"),
            nullable=False,
        ),
        sa.Column("ledger_fill_id", sa.String(160), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("occurred_at", UTC, nullable=False),
        sa.UniqueConstraint(
            "ledger_fill_id",
            name="uq_simulation_fill_ledger",
        ),
    )
    op.create_index(
        "ix_simulation_fills_order",
        "simulation_execution_fills",
        ["order_id"],
    )


def _create_fact_guards() -> None:
    dialect = op.get_context().dialect.name
    if dialect == "sqlite":
        for table in FACT_TABLES:
            op.execute(
                f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} "
                "BEGIN SELECT RAISE(ABORT, 'append-only simulation fact table'); END"
            )
            op.execute(
                f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} "
                "BEGIN SELECT RAISE(ABORT, 'append-only simulation fact table'); END"
            )
    elif dialect == "postgresql":
        op.execute(
            "CREATE OR REPLACE FUNCTION finance_god_prevent_simulation_fact_mutation() "
            "RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
            "RAISE EXCEPTION 'append-only simulation fact table'; END $$"
        )
        for table in FACT_TABLES:
            op.execute(
                f"CREATE TRIGGER {table}_no_mutation "
                f"BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW "
                "EXECUTE FUNCTION finance_god_prevent_simulation_fact_mutation()"
            )
