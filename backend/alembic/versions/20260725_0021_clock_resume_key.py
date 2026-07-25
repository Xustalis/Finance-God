"""add simulation clock resume idempotency key

Revision ID: 20260725_0021
Revises: 20260725_0020
"""

from alembic import op
import sqlalchemy as sa

revision = "20260725_0021"
down_revision = "20260725_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "simulation_clocks",
        sa.Column("last_resume_key", sa.String(length=160), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("simulation_clocks", "last_resume_key")
