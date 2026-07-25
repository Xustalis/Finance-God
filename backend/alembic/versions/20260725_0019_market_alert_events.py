"""Add owner-scoped market alert delivery and SSE event storage.

Revision ID: 20260725_0019_alert_events
Revises: 20260725_0018
Create Date: 2026-07-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260725_0019_alert_events"
down_revision = "20260725_0018"
branch_labels = None
depends_on = None

UTC = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.add_column(
        "notifications",
        sa.Column("details_json", sa.JSON(), nullable=False, server_default="{}"),
    )
    with op.batch_alter_table("notifications") as batch:
        batch.create_unique_constraint(
            "uq_notifications_owner_source",
            ["owner_user_id", "source_object_type", "source_object_id"],
        )
    op.create_table(
        "user_market_focus",
        sa.Column("owner_user_id", sa.String(160), primary_key=True),
        sa.Column("symbol", sa.String(160), nullable=False),
        sa.Column("updated_at", UTC, nullable=False),
    )
    op.create_index(
        "ix_user_market_focus_symbol", "user_market_focus", ["symbol"]
    )
    op.create_table(
        "market_alert_dispatch_outbox",
        sa.Column(
            "alert_id",
            sa.String(160),
            sa.ForeignKey("market_alerts.alert_id"),
            primary_key=True,
        ),
        sa.Column("created_at", UTC, nullable=False),
        sa.Column("dispatched_at", UTC),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.String(500)),
    )
    op.create_table(
        "user_events",
        sa.Column("cursor", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(160), nullable=False),
        sa.Column("owner_user_id", sa.String(160), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column(
            "notification_id",
            sa.String(160),
            sa.ForeignKey("notifications.notification_id"),
            nullable=False,
        ),
        sa.Column("fact_version", sa.String(160), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("occurred_at", UTC, nullable=False),
        sa.UniqueConstraint(
            "owner_user_id", "event_id", name="uq_user_events_owner_event"
        ),
    )
    op.create_index(
        "ix_user_events_owner_cursor", "user_events", ["owner_user_id", "cursor"]
    )
    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "notification_id",
            sa.String(160),
            sa.ForeignKey("notifications.notification_id"),
            nullable=False,
        ),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("delivered_at", UTC),
        sa.Column("error", sa.String(500)),
        sa.UniqueConstraint(
            "notification_id",
            "channel",
            name="uq_notification_delivery_channel",
        ),
    )
    op.create_index(
        "ix_notification_deliveries_status",
        "notification_deliveries",
        ["status"],
    )


def downgrade() -> None:
    op.drop_table("notification_deliveries")
    op.drop_table("user_events")
    op.drop_table("market_alert_dispatch_outbox")
    op.drop_table("user_market_focus")
    with op.batch_alter_table("notifications") as batch:
        batch.drop_constraint("uq_notifications_owner_source", type_="unique")
    op.drop_column("notifications", "details_json")
