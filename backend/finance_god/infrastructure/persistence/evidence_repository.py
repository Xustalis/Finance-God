from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from finance_god.domain import ConcurrentCommandConflict

from .evidence_models import EvidenceBundleRow


@dataclass(frozen=True, slots=True)
class StoredEvidence:
    """An immutable evidence bundle as persisted for one object version."""

    evidence_id: str
    owner_user_id: str
    object_type: str
    object_id: str
    version: str
    subject: str
    conclusion: str | None
    content: dict[str, object]
    lineage: dict[str, object]
    error_trace: str | None
    provider: str
    generated_at: datetime
    created_at: datetime


class EvidenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_exact(
        self, owner_user_id: str, object_type: str, object_id: str, version: str
    ) -> StoredEvidence | None:
        row = await self._session.scalar(
            select(EvidenceBundleRow).where(
                EvidenceBundleRow.owner_user_id == owner_user_id,
                EvidenceBundleRow.object_type == object_type,
                EvidenceBundleRow.object_id == object_id,
                EvidenceBundleRow.version == version,
            )
        )
        return _stored(row) if row is not None else None

    async def get_latest(
        self, owner_user_id: str, object_type: str, object_id: str
    ) -> StoredEvidence | None:
        row = await self._session.scalar(
            select(EvidenceBundleRow)
            .where(
                EvidenceBundleRow.owner_user_id == owner_user_id,
                EvidenceBundleRow.object_type == object_type,
                EvidenceBundleRow.object_id == object_id,
            )
            .order_by(EvidenceBundleRow.generated_at.desc(), EvidenceBundleRow.id.desc())
            .limit(1)
        )
        return _stored(row) if row is not None else None

    async def versions(
        self, owner_user_id: str, object_type: str, object_id: str
    ) -> list[StoredEvidence]:
        rows = await self._session.scalars(
            select(EvidenceBundleRow)
            .where(
                EvidenceBundleRow.owner_user_id == owner_user_id,
                EvidenceBundleRow.object_type == object_type,
                EvidenceBundleRow.object_id == object_id,
            )
            .order_by(EvidenceBundleRow.generated_at.asc(), EvidenceBundleRow.id.asc())
        )
        return [_stored(row) for row in rows]

    async def insert(self, stored: StoredEvidence) -> StoredEvidence:
        try:
            self._session.add(
                EvidenceBundleRow(
                    evidence_id=stored.evidence_id,
                    owner_user_id=stored.owner_user_id,
                    object_type=stored.object_type,
                    object_id=stored.object_id,
                    version=stored.version,
                    subject=stored.subject,
                    conclusion=stored.conclusion,
                    content_json=stored.content,
                    lineage_json=stored.lineage,
                    error_trace=stored.error_trace,
                    provider=stored.provider,
                    generated_at=stored.generated_at,
                    created_at=stored.created_at,
                )
            )
            await self._session.flush()
        except IntegrityError as error:
            raise ConcurrentCommandConflict(
                "an evidence bundle for this object version already exists"
            ) from error
        return stored


def _stored(row: EvidenceBundleRow) -> StoredEvidence:
    return StoredEvidence(
        evidence_id=row.evidence_id,
        owner_user_id=row.owner_user_id,
        object_type=row.object_type,
        object_id=row.object_id,
        version=row.version,
        subject=row.subject,
        conclusion=row.conclusion,
        content=dict(row.content_json),
        lineage=dict(row.lineage_json),
        error_trace=row.error_trace,
        provider=row.provider,
        generated_at=row.generated_at,
        created_at=row.created_at,
    )
