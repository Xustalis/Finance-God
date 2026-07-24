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
            # 普通字符串字面量在 PostgreSQL 与 SQLite 上均可作为 JSON 列默认值
            server_default=sa.text("'{}'"),
        ),
    )
    # SQLite 不支持 ALTER COLUMN ... DROP DEFAULT，仅在 PostgreSQL 等方言上移除服务端默认值
    if op.get_context().dialect.name != "sqlite":
        op.alter_column(
            "onboarding_sessions",
            "pending_profile_evidence",
            server_default=None,
        )
