"""Audit event writer — records all significant actions for traceability.

Per PRD requirements, every mutation of a versioned domain object must produce
an audit trail entry.  This module provides a single ``write_audit_event``
helper that services call after committing their primary business logic.

The actual ``AuditEvent`` ORM model import is **deferred** (inside the
function body) to avoid circular-import issues during early application
initialisation — the model module may itself import from ``app.core``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession


async def write_audit_event(
    db: AsyncSession,
    event_type: str,
    user_id: str | uuid.UUID,
    subject_type: str,
    subject_id: str | uuid.UUID,
    before_version: int | None = None,
    after_version: int | None = None,
    request_correlation_id: str | uuid.UUID | None = None,
    payload: dict | None = None,
    actor: str = "system",
) -> None:
    """Write an audit event to the database.

    Args:
        db: Async SQLAlchemy session.
        event_type: Category of the event (e.g. ``profile.updated``).
        user_id: The user this event belongs to.
        subject_type: Domain-object type (``profile``, ``mandate``, …).
        subject_id: Primary key of the affected object.
        before_version: Version number *before* the mutation (if versioned).
        after_version: Version number *after* the mutation (if versioned).
        request_correlation_id: Optional correlation ID from the HTTP layer.
        payload: Free-form JSON-serialisable context dict.
        actor: Who performed the action (``system``, ``user``, ``agent:xxx``).
    """
    from app.models.audit_event import AuditEvent  # deferred import

    event = AuditEvent(
        id=uuid.uuid4(),
        event_type=event_type,
        user_id=uuid.UUID(user_id) if isinstance(user_id, str) else user_id,
        subject_type=subject_type,
        subject_id=uuid.UUID(subject_id) if isinstance(subject_id, str) else subject_id,
        before_version=before_version,
        after_version=after_version,
        request_correlation_id=(
            uuid.UUID(request_correlation_id)
            if request_correlation_id and isinstance(request_correlation_id, str)
            else request_correlation_id
        ),
        payload=payload or {},
        actor=actor,
        created_at=datetime.now(timezone.utc),
    )
    db.add(event)
