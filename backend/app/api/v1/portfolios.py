"""目标组合路由 - 生成目标组合"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import ApiResponse
from app.core.security import get_current_user_id
from app.db.session import get_db
from app.services.portfolio_service import PortfolioService

router = APIRouter()


@router.post("/")
async def generate_portfolio(
    data: dict,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    service = PortfolioService(db)
    result = await service.generate(user_id, data)
    return ApiResponse.ok(result)
