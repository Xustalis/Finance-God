"""Clean initial schema for the onboarding application.

Revision ID: 20260723_0001
Revises:
Create Date: 2026-07-23
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260723_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(100)),
        sa.Column("base_currency", sa.String(3), nullable=False),
        sa.Column("region", sa.String(10), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("role IN ('user', 'admin')", name="ck_users_role"),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_users_status"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "ai_model_configs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("capability", sa.String(16), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("api_key_ref", sa.String(100)),
        sa.Column("prompt_version", sa.String(32), nullable=False),
        sa.Column("min_rounds", sa.Integer(), nullable=False),
        sa.Column("max_rounds", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("capability", name="uq_ai_model_configs_capability"),
        sa.CheckConstraint("capability IN ('text', 'stt', 'tts')", name="ck_ai_model_configs_capability"),
        sa.CheckConstraint("min_rounds BETWEEN 6 AND 12", name="ck_ai_model_configs_min_rounds"),
        sa.CheckConstraint("max_rounds BETWEEN 6 AND 12", name="ck_ai_model_configs_max_rounds"),
        sa.CheckConstraint("min_rounds <= max_rounds", name="ck_ai_model_configs_round_order"),
    )

    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("version", name="uq_prompt_versions_version"),
    )

    op.create_table(
        "admin_audit_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(36)),
        sa.Column("before_data", sa.JSON(), nullable=False),
        sa.Column("after_data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_admin_audit_records_actor_id", "admin_audit_records", ["actor_id"])

    op.create_table(
        "onboarding_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("live_key", sa.String(36), unique=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("step", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("round_count", sa.Integer(), nullable=False),
        sa.Column("turn_count", sa.Integer(), nullable=False),
        sa.Column("min_rounds", sa.Integer(), nullable=False),
        sa.Column("max_rounds", sa.Integer(), nullable=False),
        sa.Column("completeness", sa.Float(), nullable=False),
        sa.Column("provider_name", sa.String(64), nullable=False),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(32), nullable=False),
        sa.Column("prompt_id", sa.String(36), sa.ForeignKey("prompt_versions.id")),
        sa.Column("prompt_hash", sa.String(64), nullable=False),
        sa.Column("prompt_content", sa.Text(), nullable=False),
        sa.Column("objective_profile", sa.JSON(), nullable=False),
        sa.Column("dimension_scores", sa.JSON(), nullable=False),
        sa.Column("profile_evidence", sa.JSON(), nullable=False),
        sa.Column("pending_profile_evidence", sa.JSON(), nullable=False),
        sa.Column("skipped_dimensions", sa.JSON(), nullable=False),
        sa.Column("followup_counts", sa.JSON(), nullable=False),
        sa.Column("current_dimension", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('active', 'ready', 'completed')", name="ck_onboarding_sessions_status"),
        sa.CheckConstraint("round_count >= 0 AND round_count <= max_rounds", name="ck_onboarding_sessions_round_count"),
        sa.CheckConstraint("min_rounds BETWEEN 6 AND 12", name="ck_onboarding_sessions_min_rounds"),
        sa.CheckConstraint("max_rounds BETWEEN 6 AND 12", name="ck_onboarding_sessions_max_rounds"),
        sa.CheckConstraint("completeness >= 0 AND completeness <= 1", name="ck_onboarding_sessions_completeness"),
    )
    op.create_index("ix_onboarding_sessions_user_id", "onboarding_sessions", ["user_id"])
    op.create_index("ix_onboarding_sessions_status", "onboarding_sessions", ["status"])

    op.create_table(
        "profile_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("onboarding_sessions.id"), nullable=False),
        sa.Column("request_id", sa.String(36)),
        sa.Column("parent_message_id", sa.String(36), sa.ForeignKey("profile_messages.id")),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("input_mode", sa.String(16), nullable=False),
        sa.Column("target_dimension", sa.String(64)),
        sa.Column("sensitive", sa.Boolean(), nullable=False),
        sa.Column("refused", sa.Boolean(), nullable=False),
        sa.Column("extracted_data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_profile_messages_role"),
        sa.CheckConstraint("input_mode IN ('text', 'voice')", name="ck_profile_messages_input_mode"),
        sa.UniqueConstraint("session_id", "request_id", name="uq_profile_messages_request"),
    )
    op.create_index("ix_profile_messages_session_id", "profile_messages", ["session_id"])

    op.create_table(
        "investment_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("onboarding_sessions.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("objective_profile", sa.JSON(), nullable=False),
        sa.Column("dimension_scores", sa.JSON(), nullable=False),
        sa.Column("profile_evidence", sa.JSON(), nullable=False),
        sa.Column("archetype_code", sa.String(64), nullable=False),
        sa.Column("archetype_title", sa.String(100), nullable=False),
        sa.Column("risk_level", sa.String(32), nullable=False),
        sa.Column("loss_tolerance_percent", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("completeness", sa.Float(), nullable=False),
        sa.Column("education_only", sa.Boolean(), nullable=False),
        sa.Column("report_summary", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("session_id", name="uq_investment_profiles_session_id"),
        sa.UniqueConstraint("user_id", "version", name="uq_investment_profiles_user_version"),
    )
    op.create_index("ix_investment_profiles_user_id", "investment_profiles", ["user_id"])

    op.create_table(
        "direction_recommendations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("profile_id", sa.String(36), sa.ForeignKey("investment_profiles.id"), nullable=False),
        sa.Column("direction", sa.String(64), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actionable", sa.Boolean(), nullable=False),
        sa.Column("selected", sa.Boolean(), nullable=False),
        sa.Column("selected_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("profile_id", "direction", name="uq_direction_recommendations_direction"),
        sa.UniqueConstraint("profile_id", "rank", name="uq_direction_recommendations_rank"),
        sa.CheckConstraint("rank BETWEEN 1 AND 5", name="ck_direction_recommendations_rank"),
        sa.CheckConstraint("score >= 0 AND score <= 100", name="ck_direction_recommendations_score"),
    )
    op.create_index("ix_direction_recommendations_profile_id", "direction_recommendations", ["profile_id"])


def downgrade() -> None:
    op.drop_table("direction_recommendations")
    op.drop_table("investment_profiles")
    op.drop_table("profile_messages")
    op.drop_table("onboarding_sessions")
    op.drop_table("admin_audit_records")
    op.drop_table("prompt_versions")
    op.drop_table("ai_model_configs")
    op.drop_table("users")
