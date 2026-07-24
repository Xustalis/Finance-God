"""Append-only trade plan versions and planned-draft links.

Revision ID: 20260724_0012_trade_plans
Revises: 20260724_0011_candidate_ignores
Create Date: 2026-07-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from finance_god.infrastructure.persistence import trade_plan_models as _models  # noqa: F401

revision = "20260724_0012_trade_plans"
down_revision = "20260724_0011_candidate_ignores"
branch_labels = None
depends_on = None

UTC = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "trade_plan_versions",
        sa.Column("plan_id", sa.String(160), primary_key=True),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("owner_user_id", sa.String(160), nullable=False),
        sa.Column("account_id", sa.String(160), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("source_id", sa.String(160), nullable=False),
        sa.Column("creation_key", sa.String(200)),
        sa.Column("plan_json", sa.JSON(), nullable=False),
        sa.Column("data_status_json", sa.JSON(), nullable=False),
        sa.Column("created_at", UTC, nullable=False),
        sa.CheckConstraint("revision >= 1", name="ck_trade_plan_revision_positive"),
        sa.UniqueConstraint(
            "owner_user_id",
            "creation_key",
            name="uq_trade_plan_owner_creation_key",
        ),
    )
    op.create_index(
        "ix_trade_plan_versions_owner",
        "trade_plan_versions",
        ["owner_user_id"],
    )
    op.create_index(
        "ix_trade_plan_versions_status",
        "trade_plan_versions",
        ["status"],
    )
    op.create_table(
        "trade_plan_draft_links",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("plan_id", sa.String(160), nullable=False),
        sa.Column("plan_revision", sa.Integer(), nullable=False),
        sa.Column("action_id", sa.String(160), nullable=False),
        sa.Column("draft_id", sa.String(160), nullable=False),
        sa.Column("draft_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", UTC, nullable=False),
        sa.UniqueConstraint(
            "plan_id",
            "plan_revision",
            "action_id",
            name="uq_trade_plan_draft_action",
        ),
        sa.UniqueConstraint("draft_id", name="uq_trade_plan_draft_id"),
    )
    op.create_index(
        "ix_trade_plan_draft_links_plan",
        "trade_plan_draft_links",
        ["plan_id", "plan_revision"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_trade_plan_draft_links_plan",
        table_name="trade_plan_draft_links",
    )
    op.drop_table("trade_plan_draft_links")
    op.drop_index("ix_trade_plan_versions_status", table_name="trade_plan_versions")
    op.drop_index("ix_trade_plan_versions_owner", table_name="trade_plan_versions")
    op.drop_table("trade_plan_versions")
