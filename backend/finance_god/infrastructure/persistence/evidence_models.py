"""Append-only structured evidence bundles keyed by object version.

Each row captures the immutable evidence produced for one object version
(agent run, trade plan, order draft). Bundles are never mutated in place;
a new object version produces a new row so the process history stays
auditable.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base, UTCDateTime


class EvidenceBundleRow(Base):
    """One immutable evidence bundle for a single object version."""

    __tablename__ = "evidence_bundles"
    __table_args__ = (
        UniqueConstraint(
            "object_type",
            "object_id",
            "version",
            name="uq_evidence_object_version",
        ),
        UniqueConstraint("evidence_id", name="uq_evidence_id"),
        Index("ix_evidence_bundles_owner", "owner_user_id"),
        Index("ix_evidence_bundles_object", "object_type", "object_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    evidence_id: Mapped[str] = mapped_column(String(160), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(160), nullable=False)
    object_type: Mapped[str] = mapped_column(String(80), nullable=False)
    object_id: Mapped[str] = mapped_column(String(160), nullable=False)
    version: Mapped[str] = mapped_column(String(80), nullable=False)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    conclusion: Mapped[str | None] = mapped_column(String(2000))
    content_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    lineage_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    error_trace: Mapped[str | None] = mapped_column(String(8000))
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
