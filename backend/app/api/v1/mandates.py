"""投资授权书路由"""

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import ApiResponse
from app.core.security import get_current_user_id
from app.db.session import get_db
from app.services.mandate_service import MandateService

router = APIRouter()


class RevokeRequest(BaseModel):
    reason: str = ""


@router.get("/active")
async def get_active_mandate(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    service = MandateService(db)
    mandate = await service.get_active_mandate(user_id)
    return ApiResponse.ok(mandate)


@router.post("/")
async def create_mandate(
    data: dict,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    service = MandateService(db)
    mandate = await service.create_mandate(user_id, data)
    return ApiResponse.ok(mandate)


@router.post("/{mandate_id}/pause")
async def pause_mandate(
    mandate_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    service = MandateService(db)
    result = await service.pause_mandate(user_id, mandate_id)
    return ApiResponse.ok(result)


@router.post("/{mandate_id}/revoke")
async def revoke_mandate(
    mandate_id: str,
    body: RevokeRequest | None = Body(default=None),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    service = MandateService(db)
    reason = body.reason if body else ""
    result = await service.revoke_mandate(user_id, mandate_id, reason)
    return ApiResponse.ok(result)
