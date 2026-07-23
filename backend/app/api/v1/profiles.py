"""用户画像路由"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import ApiResponse
from app.core.security import get_current_user_id
from app.db.session import get_db
from app.services.profile_service import ProfileService

router = APIRouter()


@router.get("/me")
async def get_my_profile(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    service = ProfileService(db)
    profile = await service.get_profile(user_id)
    return ApiResponse.ok(profile)


@router.post("/")
async def save_profile(
    data: dict,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    service = ProfileService(db)
    profile = await service.save_profile(user_id, data)
    return ApiResponse.ok(profile)


@router.post("/{version}/confirm")
async def confirm_profile(
    version: int,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    service = ProfileService(db)
    profile = await service.confirm_profile(user_id, version)
    return ApiResponse.ok(profile)
