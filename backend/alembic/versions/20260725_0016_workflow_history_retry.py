"""workflow history and retry lineage

Revision ID: 20260725_0016
Revises: 20260725_0015_active_workflow
"""

import sqlalchemy as sa
from alembic import op

revision = "20260725_0016"
down_revision = "20260725_0015_active_workflow"
branch_labels = None
depends_on = None

UTC = sa.DateTime(timezone=True)


def _workflow_runs_table(*, include_retry_lineage: bool) -> sa.Table:
    """Describe the table explicitly so SQLite offline batch mode can render."""

    metadata = sa.MetaData()
    columns: list[sa.SchemaItem] = [
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
    ]
    if include_retry_lineage:
        columns.extend(
            (
                sa.Column(
                    "parent_run_id",
                    sa.String(160),
                    sa.ForeignKey(
                        "workflow_runs.run_id",
                        name="fk_workflow_runs_parent_run",
                    ),
                ),
                sa.Column("retry_mode", sa.String(24)),
                sa.Column("resumed_from_node_id", sa.String(160)),
                sa.CheckConstraint(
                    "retry_mode IS NULL OR retry_mode IN ('full','resume_failed')",
                    name="ck_workflow_run_retry_mode",
                ),
            )
        )
    columns.extend(
        (
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
                "trade_eligible = false OR status = 'completed'",
                name="ck_workflow_run_trade_eligible",
            ),
            sa.CheckConstraint(
                "length(request_hash) = 64",
                name="ck_workflow_run_request_hash",
            ),
        )
    )
    table = sa.Table(
        "workflow_runs",
        metadata,
        *columns,
    )
    sa.Index("ix_workflow_runs_workflow_key", table.c.workflow_key)
    sa.Index("ix_workflow_runs_status", table.c.status)
    active_statuses = (
        "'queued','running','cancel_requested','cancelling'"
    )
    sa.Index(
        "uq_workflow_run_owner_active",
        table.c.owner_id,
        unique=True,
        sqlite_where=sa.text(f"status IN ({active_statuses})"),
        postgresql_where=sa.text(f"status IN ({active_statuses})"),
    )
    return table


def upgrade() -> None:
    with op.batch_alter_table(
        "workflow_runs",
        copy_from=_workflow_runs_table(include_retry_lineage=False),
    ) as batch:
        batch.add_column(sa.Column("parent_run_id", sa.String(160), nullable=True))
        batch.add_column(sa.Column("retry_mode", sa.String(24), nullable=True))
        batch.add_column(sa.Column("resumed_from_node_id", sa.String(160), nullable=True))
        batch.create_foreign_key(
            "fk_workflow_runs_parent_run",
            "workflow_runs",
            ["parent_run_id"],
            ["run_id"],
        )
        batch.create_check_constraint(
            "ck_workflow_run_retry_mode",
            "retry_mode IS NULL OR retry_mode IN ('full','resume_failed')",
        )
    op.create_index(
        "ix_workflow_runs_owner_requested",
        "workflow_runs",
        ["owner_id", "requested_at", "run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_runs_owner_requested", table_name="workflow_runs")
    with op.batch_alter_table(
        "workflow_runs",
        copy_from=_workflow_runs_table(include_retry_lineage=True),
    ) as batch:
        batch.drop_constraint("ck_workflow_run_retry_mode", type_="check")
        batch.drop_constraint("fk_workflow_runs_parent_run", type_="foreignkey")
        batch.drop_column("resumed_from_node_id")
        batch.drop_column("retry_mode")
        batch.drop_column("parent_run_id")
