"""Enforce one active WorkflowRun per owner.

Revision ID: 20260725_0015_active_workflow
Revises: 20260724_0014_market_monitor
Create Date: 2026-07-25
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "20260725_0015_active_workflow"
down_revision = "20260724_0014_market_monitor"
branch_labels = None
depends_on = None

ACTIVE_STATUSES = ("queued", "running", "cancel_requested", "cancelling")
ACTIVE_STATUS_SQL = ", ".join(f"'{status}'" for status in ACTIVE_STATUSES)
INDEX_NAME = "uq_workflow_run_owner_active"


def upgrade() -> None:
    if not op.get_context().as_sql:
        connection = op.get_bind()
        duplicate = connection.execute(
            text(
                "SELECT owner_id, COUNT(*) AS active_count "
                "FROM workflow_runs "
                f"WHERE status IN ({ACTIVE_STATUS_SQL}) "
                "GROUP BY owner_id HAVING COUNT(*) > 1 "
                "ORDER BY owner_id LIMIT 1"
            )
        ).first()
        if duplicate is not None:
            raise RuntimeError(
                "cannot enforce one active workflow per owner: "
                f"owner {duplicate.owner_id!r} has "
                f"{duplicate.active_count} active runs"
            )
    op.create_index(
        INDEX_NAME,
        "workflow_runs",
        ["owner_id"],
        unique=True,
        postgresql_where=text(f"status IN ({ACTIVE_STATUS_SQL})"),
        sqlite_where=text(f"status IN ({ACTIVE_STATUS_SQL})"),
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="workflow_runs")
