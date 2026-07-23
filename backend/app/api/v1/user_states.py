"""用户心智状态路由"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import ApiResponse
from app.core.security import get_current_user_id
from app.db.session import get_db
from app.services.user_state_service import UserStateService

router = APIRouter()


class StateConfirmationRequest(BaseModel):
    snapshot_id: str
    action: str  # confirm/correct/reject
    feedback: str | None = None


@router.get("/latest")
async def get_latest_state(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    service = UserStateService(db)
    snapshot = await service.get_latest_snapshot(user_id)
    return ApiResponse.ok(snapshot)


@router.post("/confirmations")
async def confirm_state(
    body: StateConfirmationRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    service = UserStateService(db)
    result = await service.confirm_state(
        user_id, body.snapshot_id, body.action, body.feedback
    )
    return ApiResponse.ok(result)


@router.get("/cooldown")
async def get_cooldown(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    service = UserStateService(db)
    cooldown = await service.get_active_cooldown(user_id)
    return ApiResponse.ok(cooldown)
