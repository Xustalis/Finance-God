"""风险事件路由 - 列表查询"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import ApiResponse
from app.core.security import get_current_user_id
from app.db.session import get_db
from app.models.risk_event import RiskEvent

router = APIRouter()


@router.get("/")
async def list_risk_events(
    severity: str | None = Query(default=None),
    category: str | None = Query(default=None),
    disposition: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    conditions = [RiskEvent.user_id == user_id]
    if severity:
        conditions.append(RiskEvent.severity == severity)
    if category:
        conditions.append(RiskEvent.category == category)
    if disposition:
        conditions.append(RiskEvent.disposition == disposition)

    count_stmt = select(func.count()).select_from(RiskEvent).where(*conditions)
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        select(RiskEvent)
        .where(*conditions)
        .order_by(RiskEvent.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    events = (await db.execute(stmt)).scalars().all()
    return ApiResponse.ok(
        [_to_dict(e) for e in events],
        meta={"page": page, "page_size": page_size, "total": total},
    )


def _to_dict(event: RiskEvent) -> dict:
    return {
        "id": event.id,
        "rule_id": event.rule_id,
        "severity": event.severity,
        "category": event.category,
        "description": event.description,
        "input_snapshot": event.input_snapshot,
        "affected_objects": event.affected_objects,
        "disposition": event.disposition,
        "resolution": event.resolution,
        "resolved_at": event.resolved_at.isoformat() if event.resolved_at else None,
        "resolved_by": event.resolved_by,
        "recovery_conditions": event.recovery_conditions,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }
