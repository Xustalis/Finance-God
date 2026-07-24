"""Create workspace watchlist and notification storage.

Revision ID: 20260724_0004
Revises: 20260724_0003
Create Date: 2026-07-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from finance_god.infrastructure.persistence import workspace_models as _workspace_models  # noqa: F401

revision = "20260724_0007_finance_workspace"
down_revision = "20260724_0006_finance_execution"
branch_labels = None
depends_on = None

UTC = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "watchlist_groups",
        sa.Column("group_id", sa.String(160), primary_key=True),
        sa.Column("owner_user_id", sa.String(160), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500)),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", UTC, nullable=False),
        sa.Column("updated_at", UTC, nullable=False),
        sa.CheckConstraint(
            "revision >= 1", name="ck_watchlist_group_revision_positive"
        ),
    )
    op.create_index("ix_watchlist_groups_owner_id", "watchlist_groups", ["owner_user_id"])

    op.create_table(
        "watchlist_instruments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "group_id",
            sa.String(160),
            sa.ForeignKey("watchlist_groups.group_id"),
            nullable=False,
        ),
        sa.Column("instrument_id", sa.String(160), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("added_at", UTC, nullable=False),
        sa.Column("added_by", sa.String(160), nullable=False),
        sa.UniqueConstraint(
            "group_id", "instrument_id", name="uq_watchlist_instrument_group_instrument"
        ),
        sa.CheckConstraint(
            "revision >= 1", name="ck_watchlist_instrument_revision_positive"
        ),
    )
    op.create_index("ix_watchlist_instruments_group_id", "watchlist_instruments", ["group_id"])
    op.create_index(
        "ix_watchlist_instruments_instrument_id", "watchlist_instruments", ["instrument_id"]
    )

    op.create_table(
        "notifications",
        sa.Column("notification_id", sa.String(160), primary_key=True),
        sa.Column("owner_user_id", sa.String(160), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("message", sa.String(1000), nullable=False),
        sa.Column("source_object_type", sa.String(80), nullable=False),
        sa.Column("source_object_id", sa.String(160), nullable=False),
        sa.Column("source_version", sa.String(80), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", UTC, nullable=False),
        sa.Column("read_at", UTC),
        sa.Column("audit_id", sa.String(160), nullable=False),
        sa.Column("audit_actor_id", sa.String(160), nullable=False),
        sa.Column("audit_recorded_at", UTC, nullable=False),
        sa.CheckConstraint(
            "notification_id != 'system:required'", name="ck_notification_id_not_system"
        ),
    )
    for index_name, columns in (
        ("ix_notifications_owner_id", ["owner_user_id"]),
        ("ix_notifications_status", ["status"]),
        ("ix_notifications_category", ["category"]),
        ("ix_notifications_severity", ["severity"]),
    ):
        op.create_index(index_name, "notifications", columns)

    op.create_table(
        "notification_receipts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "notification_id",
            sa.String(160),
            sa.ForeignKey("notifications.notification_id"),
            nullable=False,
        ),
        sa.Column("owner_user_id", sa.String(160), nullable=False),
        sa.Column("read_at", UTC, nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.UniqueConstraint("notification_id", name="uq_receipt_notification"),
    )
    op.create_index(
        "ix_notification_receipts_owner_id", "notification_receipts", ["owner_user_id"]
    )

    op.create_table(
        "notification_preferences",
        sa.Column("owner_user_id", sa.String(160), primary_key=True),
        sa.Column("preferences_json", sa.JSON(), nullable=False),
        sa.Column("updated_at", UTC, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("notification_preferences")
    op.drop_table("notification_receipts")
    op.drop_table("notifications")
    op.drop_table("watchlist_instruments")
    op.drop_table("watchlist_groups")
