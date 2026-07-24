"""Investment mandate authorization store (T00).

Revision ID: 20260724_0010_investment_mandate
Revises: 20260724_0009_merge_heads
Create Date: 2026-07-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from finance_god.infrastructure.persistence import (  # noqa: F401
    mandate_models as _mandate_models,
)

revision = "20260724_0010_investment_mandate"
down_revision = "20260724_0009_merge_heads"
branch_labels = None
depends_on = None

UTC = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "investment_mandates",
        sa.Column("mandate_id", sa.String(160), primary_key=True),
        sa.Column("owner_user_id", sa.String(160), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("autonomy_level", sa.String(8), nullable=False),
        sa.Column("allowed_markets", sa.JSON(), nullable=False),
        sa.Column("allowed_assets", sa.JSON(), nullable=False),
        sa.Column("allowed_sides", sa.JSON(), nullable=False),
        sa.Column("allowed_order_types", sa.JSON(), nullable=False),
        sa.Column("short_markets", sa.JSON(), nullable=False),
        sa.Column("limits_json", sa.JSON(), nullable=False),
        sa.Column("valid_from", UTC, nullable=False),
        sa.Column("valid_until", UTC, nullable=False),
        sa.Column("created_at", UTC, nullable=False),
        sa.Column("created_by", sa.String(160), nullable=False),
        sa.Column("note", sa.String(500)),
        sa.UniqueConstraint(
            "owner_user_id", "version", name="uq_investment_mandate_owner_version"
        ),
        sa.CheckConstraint(
            "version >= 1", name="ck_investment_mandate_version_positive"
        ),
    )
    op.create_index(
        "ix_investment_mandates_owner_id", "investment_mandates", ["owner_user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_investment_mandates_owner_id", table_name="investment_mandates")
    op.drop_table("investment_mandates")
