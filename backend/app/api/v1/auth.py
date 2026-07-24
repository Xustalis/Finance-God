"""认证路由 - 登录/注册/当前用户"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import ApiResponse
from app.core.security import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.db.session import get_db
from app.models.user import User

router = APIRouter()


class LoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized or "." not in normalized.rsplit("@", 1)[-1]:
            raise ValueError("Invalid email address")
        return normalized


class RegisterRequest(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = None
    base_currency: str = "CNY"
    region: str = "CN"

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return LoginRequest.validate_email(value)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    display_name: str | None
    base_currency: str
    region: str
    role: str
    status: str
    last_login_at: datetime | None
    created_at: datetime


class AuthData(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse


@router.post("/login", response_model=ApiResponse[AuthData])
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if not user or user.status != "active" or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误",
        )
    user.last_login_at = datetime.now(timezone.utc)
    await db.flush()
    token = create_access_token(user.id)
    return ApiResponse.ok(
        {
            "access_token": token,
            "token_type": "bearer",
            "user": _user_to_dict(user),
        }
    )


@router.post("/register", response_model=ApiResponse[AuthData], status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该邮箱已被注册",
        )
    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
        display_name=body.display_name,
        base_currency=body.base_currency,
        region=body.region,
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该邮箱已被注册",
        ) from exc
    token = create_access_token(user.id)
    return ApiResponse.ok(
        {
            "access_token": token,
            "token_type": "bearer",
            "user": _user_to_dict(user),
        }
    )


@router.get("/me", response_model=ApiResponse[UserResponse])
async def me(
    user: User = Depends(get_current_user),
):
    return ApiResponse.ok(_user_to_dict(user))


def _user_to_dict(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "base_currency": user.base_currency,
        "region": user.region,
        "status": user.status,
        "role": user.role,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }
