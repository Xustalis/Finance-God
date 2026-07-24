"""JWT 认证与安全工具"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import get_db

if TYPE_CHECKING:
    from app.models.user import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(user_id: str, expires_delta: timedelta | None = None) -> str:
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    payload = {"sub": user_id, "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_access_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        subject = payload.get("sub")
        return subject if isinstance(subject, str) and subject else None
    except JWTError:
        return None


async def resolve_active_user(
    token: str,
    db: AsyncSession,
) -> User | None:
    """Resolve a signed token to its current active database user."""
    from app.models.user import User

    user_id = decode_access_token(token)
    if not user_id:
        return None
    return await db.scalar(
        select(User).where(User.id == user_id, User.status == "active")
    )


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    user = await resolve_active_user(token, db)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User is inactive or missing")
    return user


async def get_current_user_id(
    user: User = Depends(get_current_user),
) -> str:
    return user.id


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator role required")
    return user


async def get_current_user_with_db(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> tuple[str, AsyncSession]:
    """同时获取用户ID和DB会话"""
    return user.id, db
