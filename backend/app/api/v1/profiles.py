from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.onboarding import serialize_profile, serialize_recommendation
from app.core.response import ApiResponse
from app.core.security import get_current_user
from app.db.session import get_db
from app.models.profile import DirectionRecommendation, InvestmentProfile
from app.models.user import User
from app.schemas.onboarding import DirectionSelectionInput, DirectionSelectionResponse, ProfileWithRecommendationsResponse

router = APIRouter()


@router.get("/me/latest", response_model=ApiResponse[ProfileWithRecommendationsResponse])
async def latest_profile(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ApiResponse:
    profile = await db.scalar(
        select(InvestmentProfile)
        .where(InvestmentProfile.user_id == user.id)
        .order_by(InvestmentProfile.version.desc())
    )
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Investment profile not found")
    recommendations = (
        await db.scalars(
            select(DirectionRecommendation)
            .where(DirectionRecommendation.profile_id == profile.id)
            .order_by(DirectionRecommendation.rank)
        )
    ).all()
    return ApiResponse.ok(
        {"profile": serialize_profile(profile), "recommendations": [serialize_recommendation(item) for item in recommendations]}
    )


@router.post("/{profile_id}/direction-selection", response_model=ApiResponse[DirectionSelectionResponse])
async def select_direction(
    profile_id: str,
    body: DirectionSelectionInput,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    profile = await db.scalar(
        select(InvestmentProfile).where(
            InvestmentProfile.id == profile_id, InvestmentProfile.user_id == user.id
        )
    )
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Investment profile not found")
    if profile.education_only:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Minor profiles cannot select an investment direction")
    recommendation = await db.scalar(
        select(DirectionRecommendation).where(
            DirectionRecommendation.profile_id == profile.id,
            DirectionRecommendation.direction == body.selected_direction.value,
        )
    )
    if recommendation is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Direction was not recommended")
    await db.execute(
        update(DirectionRecommendation)
        .where(DirectionRecommendation.profile_id == profile.id)
        .values(selected=False, selected_at=None)
    )
    recommendation.selected = True
    recommendation.selected_at = datetime.now(timezone.utc)
    await db.flush()
    result = serialize_recommendation(recommendation)
    result["selected_direction"] = recommendation.direction
    return ApiResponse.ok(result)
