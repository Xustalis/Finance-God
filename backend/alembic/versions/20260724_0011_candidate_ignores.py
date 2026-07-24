"""Create candidate ignore feedback storage.

Revision ID: 20260724_0011_candidate_ignores
Revises: 20260724_0010_investment_mandate
Create Date: 2026-07-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from finance_god.infrastructure.persistence import workspace_models as _workspace_models  # noqa: F401

revision = "20260724_0011_candidate_ignores"
down_revision = "20260724_0010_investment_mandate"
branch_labels = None
depends_on = None

UTC = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "candidate_ignores",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_user_id", sa.String(160), nullable=False),
        sa.Column("instrument_id", sa.String(160), nullable=False),
        sa.Column("reason", sa.String(64), nullable=False),
        sa.Column("note", sa.String(500)),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", UTC, nullable=False),
        sa.Column("updated_at", UTC, nullable=False),
        sa.UniqueConstraint(
            "owner_user_id",
            "instrument_id",
            name="uq_candidate_ignore_owner_instrument",
        ),
        sa.CheckConstraint(
            "revision >= 1", name="ck_candidate_ignore_revision_positive"
        ),
    )
    op.create_index(
        "ix_candidate_ignores_owner_id", "candidate_ignores", ["owner_user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_candidate_ignores_owner_id", table_name="candidate_ignores")
    op.drop_table("candidate_ignores")
