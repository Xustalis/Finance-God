"""审计事件路由 - 列表查询"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import ApiResponse
from app.core.security import get_current_user_id
from app.db.session import get_db
from app.models.audit_event import AuditEvent

router = APIRouter()


@router.get("/")
async def list_audit_events(
    event_type: str | None = Query(default=None),
    subject_type: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    conditions = [AuditEvent.user_id == user_id]
    if event_type:
        conditions.append(AuditEvent.event_type == event_type)
    if subject_type:
        conditions.append(AuditEvent.subject_type == subject_type)

    count_stmt = select(func.count()).select_from(AuditEvent).where(*conditions)
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        select(AuditEvent)
        .where(*conditions)
        .order_by(AuditEvent.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    events = (await db.execute(stmt)).scalars().all()
    return ApiResponse.ok(
        [_to_dict(e) for e in events],
        meta={"page": page, "page_size": page_size, "total": total},
    )


def _to_dict(event: AuditEvent) -> dict:
    return {
        "id": event.id,
        "event_type": event.event_type,
        "user_id": event.user_id,
        "subject_type": event.subject_type,
        "subject_id": event.subject_id,
        "before_version": event.before_version,
        "after_version": event.after_version,
        "request_correlation_id": event.request_correlation_id,
        "payload": event.payload,
        "actor": event.actor,
        "ip_address": event.ip_address,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }
