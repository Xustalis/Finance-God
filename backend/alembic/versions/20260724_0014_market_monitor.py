"""Server-side market monitor: latest snapshots and the global alert log.

Revision ID: 20260724_0014_market_monitor
Revises: 20260724_0013_evidence_bundles
Create Date: 2026-07-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from finance_god.infrastructure.persistence import (
    market_monitor_models as _models,  # noqa: F401
)

revision = "20260724_0014_market_monitor"
down_revision = "20260724_0013_evidence_bundles"
branch_labels = None
depends_on = None

UTC = sa.DateTime(timezone=True)
_PRICE = sa.Numeric(28, 8)
_RATE = sa.Numeric(28, 12)


def upgrade() -> None:
    op.create_table(
        "market_snapshots",
        sa.Column("symbol", sa.String(160), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("last", _PRICE, nullable=False),
        sa.Column("change_percent", _RATE),
        sa.Column("provider_time", sa.String(80), nullable=False),
        sa.Column("frequency", sa.String(40), nullable=False),
        sa.Column("freshness", sa.String(40), nullable=False),
        sa.Column("retrieved_at", UTC, nullable=False),
        sa.Column("updated_at", UTC, nullable=False),
    )
    op.create_table(
        "market_alerts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("alert_id", sa.String(160), nullable=False),
        sa.Column("symbol", sa.String(160), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("change_percent", _RATE, nullable=False),
        sa.Column("last", _PRICE, nullable=False),
        sa.Column("message", sa.String(1000), nullable=False),
        sa.Column("provider_time", sa.String(80), nullable=False),
        sa.Column("detected_at", UTC, nullable=False),
        sa.UniqueConstraint("alert_id", name="uq_market_alert_id"),
    )
    op.create_index(
        "ix_market_alerts_detected_at",
        "market_alerts",
        ["detected_at"],
    )
    op.create_index(
        "ix_market_alerts_symbol",
        "market_alerts",
        ["symbol"],
    )


def downgrade() -> None:
    op.drop_index("ix_market_alerts_symbol", table_name="market_alerts")
    op.drop_index("ix_market_alerts_detected_at", table_name="market_alerts")
    op.drop_table("market_alerts")
    op.drop_table("market_snapshots")
