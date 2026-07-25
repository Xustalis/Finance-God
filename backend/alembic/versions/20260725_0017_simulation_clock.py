"""account-level historical simulation clock

Revision ID: 20260725_0017
Revises: 20260725_0016
"""

from alembic import op
import sqlalchemy as sa

revision = "20260725_0017"
down_revision = "20260725_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "simulation_clocks",
        sa.Column("account_id", sa.String(length=160), nullable=False),
        sa.Column("simulation_start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("real_anchor_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("speed", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.CheckConstraint("speed = 1", name="ck_simulation_clock_speed"),
        sa.CheckConstraint(
            "status IN ('running','paused_market_closed')",
            name="ck_simulation_clock_status",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_simulation_clock_revision"),
        sa.ForeignKeyConstraint(["account_id"], ["simulation_accounts.account_id"]),
        sa.PrimaryKeyConstraint("account_id"),
    )


def downgrade() -> None:
    op.drop_table("simulation_clocks")
