"""persistent simulation protective strategies

Revision ID: 20260725_0018
Revises: 20260725_0017
"""

import sqlalchemy as sa
from alembic import op

revision = "20260725_0018"
down_revision = "20260725_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "simulation_protective_strategies",
        sa.Column("strategy_id", sa.String(length=160), nullable=False),
        sa.Column("owner_id", sa.String(length=160), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("instrument_id", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "revision >= 1", name="ck_simulation_strategy_revision"
        ),
        sa.PrimaryKeyConstraint("strategy_id"),
        sa.UniqueConstraint(
            "owner_id",
            "idempotency_key",
            name="uq_simulation_strategy_owner_idempotency",
        ),
    )
    op.create_index(
        "ix_simulation_strategies_owner",
        "simulation_protective_strategies",
        ["owner_id"],
    )
    op.create_index(
        "ix_simulation_strategies_symbol_status",
        "simulation_protective_strategies",
        ["instrument_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_simulation_strategies_symbol_status",
        table_name="simulation_protective_strategies",
    )
    op.drop_index(
        "ix_simulation_strategies_owner",
        table_name="simulation_protective_strategies",
    )
    op.drop_table("simulation_protective_strategies")
