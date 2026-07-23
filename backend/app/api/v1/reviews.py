"""复盘路由 - 列表/创建"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import ApiResponse
from app.core.security import get_current_user_id
from app.db.session import get_db
from app.services.review_service import ReviewService

router = APIRouter()


@router.get("/")
async def list_reviews(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    service = ReviewService(db)
    result = await service.list_reviews(user_id, page=page, page_size=page_size)
    return ApiResponse.ok(
        result.get("items", []),
        meta={
            "page": page,
            "page_size": page_size,
            "total": result.get("total", 0),
        },
    )


@router.post("/")
async def create_review(
    data: dict,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    service = ReviewService(db)
    result = await service.create_review(user_id, data)
    return ApiResponse.ok(result)
