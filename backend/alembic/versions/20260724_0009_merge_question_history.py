"""Merge onboarding question history and trading runtime migration heads.

Revision ID: 20260724_0009_merge_heads
Revises: 20260724_0004, 20260724_0008_direction_selected
Create Date: 2026-07-24
"""

from collections.abc import Sequence


revision: str = "20260724_0009_merge_heads"
down_revision: tuple[str, str] = (
    "20260724_0004",
    "20260724_0008_direction_selected",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
