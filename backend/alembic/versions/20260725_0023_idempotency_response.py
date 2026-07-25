"""Store replayable JSON responses for shared idempotency records.

Revision ID: 20260725_0023
Revises: 20260725_0022
Create Date: 2026-07-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260725_0023"
down_revision = "20260725_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "idempotency_records",
        sa.Column("response_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("idempotency_records", "response_json")
