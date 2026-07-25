"""Create isolated Injective Bridge persistence tables.

Revision ID: 20260725_0001
Revises:
Create Date: 2026-07-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260725_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PLAN_STATUSES = (
    "'draft', 'reviewed', 'confirmed', 'submitted', 'rejected', 'expired', 'submission_failed'"
)
ORDER_STATUSES = (
    "'broadcasting', 'broadcast', 'open', 'partially_filled', 'filled', "
    "'cancelled', 'rejected', 'unknown'"
)


def upgrade() -> None:
    op.create_table(
        "source_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_plan_id", sa.String(length=160), nullable=False),
        sa.Column("source_draft_id", sa.String(length=160), nullable=True),
        sa.Column("source_plan_version", sa.String(length=80), nullable=True),
        sa.Column("source_plan_status", sa.String(length=80), nullable=True),
        sa.Column("source_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("audit_reference", sa.String(length=255), nullable=True),
        sa.Column("draft_status", sa.String(length=80), nullable=True),
        sa.Column("draft_confirmed", sa.Boolean(), nullable=True),
        sa.Column("classification", sa.String(length=32), nullable=False),
        sa.Column("asset_domain", sa.String(length=64), nullable=False),
        sa.Column("normalized_hash", sa.String(length=64), nullable=False),
        sa.Column("projection", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "classification = 'context_only'",
            name="ck_source_snapshots_source_snapshot_context_only",
        ),
        sa.CheckConstraint(
            "asset_domain = 'non_executable_asset_domain'",
            name="ck_source_snapshots_source_snapshot_non_executable",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_source_snapshots"),
        sa.UniqueConstraint("normalized_hash", name="uq_source_snapshots_normalized_hash"),
    )
    op.create_index(
        "ix_source_snapshots_source_plan_id",
        "source_snapshots",
        ["source_plan_id"],
        unique=False,
    )

    op.create_table(
        "injective_plans",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("market_id", sa.String(length=80), nullable=False),
        sa.Column("ticker", sa.String(length=40), nullable=False),
        sa.Column("source_snapshot_id", sa.String(length=36), nullable=True),
        sa.Column("side", sa.String(length=4), nullable=False),
        sa.Column("order_type", sa.String(length=16), nullable=False),
        sa.Column("time_in_force", sa.String(length=16), nullable=False),
        sa.Column("price", sa.Numeric(precision=50, scale=18), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=50, scale=18), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("risk_report", sa.JSON(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "side IN ('buy', 'sell')", name="ck_injective_plans_injective_plan_side"
        ),
        sa.CheckConstraint(
            "order_type = 'limit'", name="ck_injective_plans_injective_plan_limit_only"
        ),
        sa.CheckConstraint(
            "time_in_force = 'gtc'", name="ck_injective_plans_injective_plan_gtc_only"
        ),
        sa.CheckConstraint("price > 0", name="ck_injective_plans_injective_plan_price_positive"),
        sa.CheckConstraint(
            "quantity > 0",
            name="ck_injective_plans_injective_plan_quantity_positive",
        ),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_injective_plans_injective_plan_revision_positive",
        ),
        sa.CheckConstraint(
            f"status IN ({PLAN_STATUSES})",
            name="ck_injective_plans_injective_plan_status",
        ),
        sa.ForeignKeyConstraint(
            ["source_snapshot_id"],
            ["source_snapshots.id"],
            name="fk_injective_plans_source_snapshot_id_source_snapshots",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_injective_plans"),
    )
    op.create_index(
        "ix_injective_plans_expires_at",
        "injective_plans",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_injective_plans_market_id",
        "injective_plans",
        ["market_id"],
        unique=False,
    )
    op.create_index(
        "ix_injective_plans_source_snapshot_id",
        "injective_plans",
        ["source_snapshot_id"],
        unique=False,
    )
    op.create_index(
        "ix_injective_plans_status",
        "injective_plans",
        ["status"],
        unique=False,
    )

    op.create_table(
        "injective_orders",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column("market_id", sa.String(length=80), nullable=False),
        sa.Column("subaccount_id", sa.String(length=80), nullable=False),
        sa.Column("client_order_id", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("tx_hash", sa.String(length=128), nullable=True),
        sa.Column("order_hash", sa.String(length=128), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=50, scale=18), nullable=False),
        sa.Column("filled_quantity", sa.Numeric(precision=50, scale=18), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("chain_projection", sa.JSON(), nullable=True),
        sa.Column("last_chain_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"status IN ({ORDER_STATUSES})",
            name="ck_injective_orders_injective_order_status",
        ),
        sa.CheckConstraint(
            "filled_quantity >= 0",
            name="ck_injective_orders_injective_order_filled_quantity_nonnegative",
        ),
        sa.CheckConstraint(
            "filled_quantity <= quantity",
            name="ck_injective_orders_injective_order_filled_quantity_lte_quantity",
        ),
        sa.CheckConstraint(
            "quantity > 0",
            name="ck_injective_orders_injective_order_quantity_positive",
        ),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_injective_orders_injective_order_revision_positive",
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["injective_plans.id"],
            name="fk_injective_orders_plan_id_injective_plans",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_injective_orders"),
        sa.UniqueConstraint("order_hash", name="uq_injective_orders_order_hash"),
        sa.UniqueConstraint("plan_id", name="uq_injective_orders_plan_id"),
        sa.UniqueConstraint("tx_hash", name="uq_injective_orders_tx_hash"),
        sa.UniqueConstraint(
            "client_order_id",
            name="uq_injective_orders_client_order_id",
        ),
    )
    op.create_index(
        "ix_injective_orders_market_id",
        "injective_orders",
        ["market_id"],
        unique=False,
    )
    op.create_index(
        "ix_injective_orders_status",
        "injective_orders",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_injective_orders_subaccount_id",
        "injective_orders",
        ["subaccount_id"],
        unique=False,
    )
    op.create_index(
        "ix_injective_orders_subaccount_status",
        "injective_orders",
        ["subaccount_id", "status"],
        unique=False,
    )

    op.create_table(
        "order_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("order_id", sa.String(length=36), nullable=False),
        sa.Column("event_key", sa.String(length=255), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"status IN ({ORDER_STATUSES})",
            name="ck_order_events_order_event_status",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["injective_orders.id"],
            name="fk_order_events_order_id_injective_orders",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_order_events"),
        sa.UniqueConstraint(
            "event_key",
            "payload_hash",
            name="uq_order_event_source_payload",
        ),
    )
    op.create_index(
        "ix_order_events_order_id",
        "order_events",
        ["order_id"],
        unique=False,
    )

    op.create_table(
        "broadcast_attempts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column("order_id", sa.String(length=36), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("tx_hash", sa.String(length=128), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('started', 'broadcast', 'failed', 'unknown')",
            name="ck_broadcast_attempts_broadcast_attempt_status",
        ),
        sa.CheckConstraint(
            "attempt_no >= 1",
            name="ck_broadcast_attempts_broadcast_attempt_number_positive",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["injective_orders.id"],
            name="fk_broadcast_attempts_order_id_injective_orders",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["injective_plans.id"],
            name="fk_broadcast_attempts_plan_id_injective_plans",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_broadcast_attempts"),
        sa.UniqueConstraint(
            "order_id",
            "attempt_no",
            name="uq_broadcast_order_attempt",
        ),
    )
    op.create_index(
        "ix_broadcast_attempts_order_id",
        "broadcast_attempts",
        ["order_id"],
        unique=False,
    )
    op.create_index(
        "ix_broadcast_attempts_plan_id",
        "broadcast_attempts",
        ["plan_id"],
        unique=False,
    )

    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("operation", sa.String(length=120), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("response_code", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.JSON(), nullable=True),
        sa.Column("resource_type", sa.String(length=80), nullable=True),
        sa.Column("resource_id", sa.String(length=160), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('in_progress', 'completed', 'failed')",
            name="ck_idempotency_records_idempotency_status",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_idempotency_records"),
        sa.UniqueConstraint(
            "operation",
            "idempotency_key",
            name="uq_idempotency_operation_key",
        ),
    )


def downgrade() -> None:
    op.drop_table("idempotency_records")
    op.drop_index("ix_broadcast_attempts_plan_id", table_name="broadcast_attempts")
    op.drop_index("ix_broadcast_attempts_order_id", table_name="broadcast_attempts")
    op.drop_table("broadcast_attempts")
    op.drop_index("ix_order_events_order_id", table_name="order_events")
    op.drop_table("order_events")
    op.drop_index("ix_injective_orders_subaccount_status", table_name="injective_orders")
    op.drop_index("ix_injective_orders_subaccount_id", table_name="injective_orders")
    op.drop_index("ix_injective_orders_status", table_name="injective_orders")
    op.drop_index("ix_injective_orders_market_id", table_name="injective_orders")
    op.drop_table("injective_orders")
    op.drop_index("ix_injective_plans_status", table_name="injective_plans")
    op.drop_index("ix_injective_plans_source_snapshot_id", table_name="injective_plans")
    op.drop_index("ix_injective_plans_market_id", table_name="injective_plans")
    op.drop_index("ix_injective_plans_expires_at", table_name="injective_plans")
    op.drop_table("injective_plans")
    op.drop_index("ix_source_snapshots_source_plan_id", table_name="source_snapshots")
    op.drop_table("source_snapshots")
