"""Persist the server-owned onboarding question.

Revision ID: 20260724_0002
Revises: 20260723_0001
"""

from alembic import op
import sqlalchemy as sa


revision: str = "20260724_0002"
down_revision: str | None = "20260723_0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("onboarding_sessions",
        sa.Column("current_question", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("onboarding_sessions", "current_question")
