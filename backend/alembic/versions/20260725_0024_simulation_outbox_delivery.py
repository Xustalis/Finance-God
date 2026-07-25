"""Track simulation outbox delivery attempts and errors.

Revision ID: 20260725_0024
Revises: 20260725_0023
Create Date: 2026-07-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260725_0024"
down_revision = "20260725_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("simulation_execution_outbox") as batch:
        batch.add_column(
            sa.Column(
                "attempt_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch.add_column(
            sa.Column(
                "last_attempt_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch.add_column(
            sa.Column("last_error", sa.String(length=2_000), nullable=True)
        )
        batch.create_check_constraint(
            "ck_simulation_execution_outbox_attempt_count",
            "attempt_count >= 0",
        )


def downgrade() -> None:
    with op.batch_alter_table("simulation_execution_outbox") as batch:
        batch.drop_constraint(
            "ck_simulation_execution_outbox_attempt_count",
            type_="check",
        )
        batch.drop_column("last_error")
        batch.drop_column("last_attempt_at")
        batch.drop_column("attempt_count")
