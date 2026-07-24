"""Record the asked question history per session.

Revision ID: 20260724_0004
Revises: 20260724_0003
"""

from alembic import op
import sqlalchemy as sa


revision: str = "20260724_0004"
down_revision: str | None = "20260724_0003"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("onboarding_sessions",
        sa.Column(
            "question_history",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )
    op.alter_column(
        "onboarding_sessions",
        "question_history",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column("onboarding_sessions", "question_history")
