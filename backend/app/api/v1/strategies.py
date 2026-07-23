"""策略路由 - 生成策略方案/暂停"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import ApiResponse
from app.core.security import get_current_user_id
from app.db.session import get_db
from app.services.strategy_service import StrategyService

router = APIRouter()


@router.post("/")
async def generate_strategy(
    data: dict,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    service = StrategyService(db)
    result = await service.generate_proposal(user_id, data)
    return ApiResponse.ok(result)


@router.post("/pause")
async def pause_strategies(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    service = StrategyService(db)
    result = await service.pause(user_id)
    return ApiResponse.ok(result)
