"""Remove the obsolete pending evidence state.

Revision ID: 20260724_0003
Revises: 20260724_0002
"""

from alembic import op
import sqlalchemy as sa


revision: str = "20260724_0003"
down_revision: str | None = "20260724_0002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.drop_column("onboarding_sessions", "pending_profile_evidence")


def downgrade() -> None:
    op.add_column("onboarding_sessions",
        sa.Column(
            "pending_profile_evidence",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
    )
    op.alter_column(
        "onboarding_sessions",
        "pending_profile_evidence",
        server_default=None,
    )
