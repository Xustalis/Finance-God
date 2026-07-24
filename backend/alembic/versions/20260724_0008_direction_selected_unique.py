"""每画像至多一条被选中的方向推荐（部分唯一索引）

Revision ID: 20260724_0008_direction_selected
Revises: 20260724_0007_finance_workspace
Create Date: 2026-07-24
"""

import sqlalchemy as sa
from alembic import op

revision = "20260724_0008_direction_selected"
down_revision = "20260724_0007_finance_workspace"
branch_labels = None
depends_on = None

INDEX_NAME = "uq_direction_recommendations_selected_one"
TABLE_NAME = "direction_recommendations"


def upgrade() -> None:
    # 部分唯一索引：仅约束 selected 为真的行，SQLite 与 PostgreSQL
    # 均支持 "WHERE selected" 写法（SQLite 布尔以整数存储，真值判断兼容）。
    op.create_index(
        INDEX_NAME,
        TABLE_NAME,
        ["profile_id"],
        unique=True,
        sqlite_where=sa.text("selected"),
        postgresql_where=sa.text("selected"),
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name=TABLE_NAME)
