"""initial schema for Finance-God domain models

Revision ID: 20260723_0001
Revises:
Create Date: 2026-07-23

Creates all ORM tables from SQLAlchemy metadata so the schema stays aligned
with app.models. Subsequent revisions should use autogenerate diffs.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260723_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ensure all models are imported and registered on Base.metadata
    import app.models  # noqa: F401
    from app.models.base import Base

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    import app.models  # noqa: F401
    from app.models.base import Base

    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
