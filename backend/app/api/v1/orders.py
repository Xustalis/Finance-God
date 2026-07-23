"""订单路由 - 列表/创建意图/提交仿真"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import ApiResponse
from app.core.security import get_current_user_id
from app.db.session import get_db
from app.models.order import OrderIntent
from app.services.execution_service import ExecutionService

router = APIRouter()


@router.get("/")
async def list_orders(
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    conditions = [OrderIntent.user_id == user_id]
    if status:
        conditions.append(OrderIntent.status == status)

    count_stmt = select(func.count()).select_from(OrderIntent).where(*conditions)
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        select(OrderIntent)
        .where(*conditions)
        .order_by(OrderIntent.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    orders = (await db.execute(stmt)).scalars().all()
    return ApiResponse.ok(
        [_to_dict(o) for o in orders],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@router.post("/")
async def create_order(
    data: dict,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    service = ExecutionService(db)
    result = await service.create_order_intent(user_id, data)
    return ApiResponse.ok(result)


@router.post("/{order_id}/submit")
async def submit_order(
    order_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    service = ExecutionService(db)
    result = await service.submit_order(user_id, order_id)
    return ApiResponse.ok(result)


def _to_dict(order: OrderIntent) -> dict:
    return {
        "id": order.id,
        "idempotency_key": order.idempotency_key,
        "account_type": order.account_type,
        "instrument_id": order.instrument_id,
        "symbol": order.symbol,
        "direction": order.direction,
        "quantity": float(order.quantity),
        "price_limit": float(order.price_limit) if order.price_limit else None,
        "price_protection": order.price_protection,
        "mandate_version": order.mandate_version,
        "portfolio_version": order.portfolio_version,
        "strategy_version": order.strategy_version,
        "risk_check_1": order.risk_check_1,
        "risk_check_2": order.risk_check_2,
        "risk_check_3": order.risk_check_3,
        "status": order.status,
        "expires_at": order.expires_at.isoformat() if order.expires_at else None,
        "cancel_reason": order.cancel_reason,
        "blocked_by": order.blocked_by,
        "created_at": order.created_at.isoformat() if order.created_at else None,
    }
