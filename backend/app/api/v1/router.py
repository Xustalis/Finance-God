from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.admin import router as admin_router
from app.api.v1.onboarding import router as onboarding_router
from app.api.v1.profiles import router as profiles_router
from app.core.response import STANDARD_ERROR_RESPONSES

api_router = APIRouter()
api_router.include_router(auth_router, prefix="/auth", tags=["auth"], responses=STANDARD_ERROR_RESPONSES)
api_router.include_router(onboarding_router, prefix="/onboarding", tags=["onboarding"], responses=STANDARD_ERROR_RESPONSES)
api_router.include_router(profiles_router, prefix="/profiles", tags=["profiles"], responses=STANDARD_ERROR_RESPONSES)
api_router.include_router(admin_router, prefix="/admin", tags=["admin"], responses=STANDARD_ERROR_RESPONSES)
