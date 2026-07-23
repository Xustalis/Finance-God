"""审计事件写入工具"""

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_event import AuditEvent


async def write_audit_event(
    db: AsyncSession,
    event_type: str,
    user_id: str,
    subject_type: str,
    subject_id: str,
    before_version: int | None = None,
    after_version: int | None = None,
    request_correlation_id: str | None = None,
    payload: dict | None = None,
    actor: str = "system",
):
    """写入审计事件"""
    event = AuditEvent(
        id=str(uuid.uuid4()),
        event_type=event_type,
        user_id=user_id,
        subject_type=subject_type,
        subject_id=subject_id,
        before_version=before_version,
        after_version=after_version,
        request_correlation_id=request_correlation_id,
        payload=payload or {},
        actor=actor,
    )
    db.add(event)
    await db.flush()
    return event
