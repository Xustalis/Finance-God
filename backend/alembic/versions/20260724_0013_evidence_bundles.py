"""Append-only structured evidence bundles keyed by object version.

Revision ID: 20260724_0013_evidence_bundles
Revises: 20260724_0012_trade_plans
Create Date: 2026-07-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from finance_god.infrastructure.persistence import (
    evidence_models as _models,  # noqa: F401
)

revision = "20260724_0013_evidence_bundles"
down_revision = "20260724_0012_trade_plans"
branch_labels = None
depends_on = None

UTC = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "evidence_bundles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("evidence_id", sa.String(160), nullable=False),
        sa.Column("owner_user_id", sa.String(160), nullable=False),
        sa.Column("object_type", sa.String(80), nullable=False),
        sa.Column("object_id", sa.String(160), nullable=False),
        sa.Column("version", sa.String(80), nullable=False),
        sa.Column("subject", sa.String(500), nullable=False),
        sa.Column("conclusion", sa.String(2000)),
        sa.Column("content_json", sa.JSON(), nullable=False),
        sa.Column("lineage_json", sa.JSON(), nullable=False),
        sa.Column("error_trace", sa.String(8000)),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("generated_at", UTC, nullable=False),
        sa.Column("created_at", UTC, nullable=False),
        sa.UniqueConstraint(
            "object_type",
            "object_id",
            "version",
            name="uq_evidence_object_version",
        ),
        sa.UniqueConstraint("evidence_id", name="uq_evidence_id"),
    )
    op.create_index(
        "ix_evidence_bundles_owner",
        "evidence_bundles",
        ["owner_user_id"],
    )
    op.create_index(
        "ix_evidence_bundles_object",
        "evidence_bundles",
        ["object_type", "object_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_evidence_bundles_object", table_name="evidence_bundles")
    op.drop_index("ix_evidence_bundles_owner", table_name="evidence_bundles")
    op.drop_table("evidence_bundles")
