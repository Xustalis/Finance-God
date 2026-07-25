"""trade decision journal and review loop

Revision ID: 20260725_0019
Revises: 20260725_0018
"""

import sqlalchemy as sa
from alembic import context, op

revision = "20260725_0019"
down_revision = "20260725_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    profile_columns = (
        sa.Column("parent_profile_id", sa.String(36), nullable=True),
        sa.Column(
            "source_type",
            sa.String(32),
            nullable=False,
            server_default="onboarding",
        ),
        sa.Column("source_id", sa.String(160), nullable=True),
    )
    if context.is_offline_mode():
        op.alter_column(
            "investment_profiles",
            "session_id",
            existing_type=sa.String(36),
            nullable=True,
        )
        for column in profile_columns:
            op.add_column("investment_profiles", column)
        op.create_foreign_key(
            "fk_profile_parent",
            "investment_profiles",
            "investment_profiles",
            ["parent_profile_id"],
            ["id"],
        )
    else:
        with op.batch_alter_table("investment_profiles") as batch:
            batch.alter_column(
                "session_id", existing_type=sa.String(36), nullable=True
            )
            for column in profile_columns:
                batch.add_column(column)
            batch.create_foreign_key(
                "fk_profile_parent",
                "investment_profiles",
                ["parent_profile_id"],
                ["id"],
            )

    op.create_table(
        "trade_episodes",
        sa.Column("episode_id", sa.String(160), primary_key=True),
        sa.Column("owner_id", sa.String(160), nullable=False),
        sa.Column("account_id", sa.String(160), nullable=False),
        sa.Column("instrument_id", sa.String(160), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("review_status", sa.String(24), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("revision >= 1", name="ck_trade_episode_revision"),
    )
    op.create_index(
        "ix_trade_episode_owner_updated",
        "trade_episodes",
        ["owner_id", "updated_at"],
    )
    op.create_index(
        "uq_trade_episode_open",
        "trade_episodes",
        ["owner_id", "account_id", "instrument_id"],
        unique=True,
        sqlite_where=sa.text("status = 'open'"),
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_table(
        "trade_decision_snapshots",
        sa.Column("snapshot_id", sa.String(160), primary_key=True),
        sa.Column(
            "episode_id",
            sa.String(160),
            sa.ForeignKey("trade_episodes.episode_id"),
            nullable=False,
        ),
        sa.Column("owner_id", sa.String(160), nullable=False),
        sa.Column("order_id", sa.String(160), nullable=False),
        sa.Column("fill_id", sa.String(160), nullable=False, unique=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_trade_decision_episode_time",
        "trade_decision_snapshots",
        ["episode_id", "occurred_at"],
    )
    op.create_table(
        "trade_reviews",
        sa.Column("review_id", sa.String(160), primary_key=True),
        sa.Column(
            "episode_id",
            sa.String(160),
            sa.ForeignKey("trade_episodes.episode_id"),
            nullable=False,
        ),
        sa.Column("owner_id", sa.String(160), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("episode_id", "kind", name="uq_trade_review_episode_kind"),
    )
    op.create_index(
        "ix_trade_review_owner_status", "trade_reviews", ["owner_id", "status"]
    )
    op.create_table(
        "trade_profile_feedback",
        sa.Column("feedback_id", sa.String(160), primary_key=True),
        sa.Column("owner_id", sa.String(160), nullable=False),
        sa.Column(
            "episode_id",
            sa.String(160),
            sa.ForeignKey("trade_episodes.episode_id"),
            nullable=False,
        ),
        sa.Column(
            "review_id",
            sa.String(160),
            sa.ForeignKey("trade_reviews.review_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("trade_profile_feedback")
    op.drop_index("ix_trade_review_owner_status", table_name="trade_reviews")
    op.drop_table("trade_reviews")
    op.drop_index(
        "ix_trade_decision_episode_time", table_name="trade_decision_snapshots"
    )
    op.drop_table("trade_decision_snapshots")
    op.drop_index("uq_trade_episode_open", table_name="trade_episodes")
    op.drop_index("ix_trade_episode_owner_updated", table_name="trade_episodes")
    op.drop_table("trade_episodes")
    with op.batch_alter_table("investment_profiles") as batch:
        batch.drop_constraint("fk_profile_parent", type_="foreignkey")
        batch.drop_column("source_id")
        batch.drop_column("source_type")
        batch.drop_column("parent_profile_id")
        batch.alter_column("session_id", existing_type=sa.String(36), nullable=False)
