"""Shared development-only account seeding."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.user import User


async def seed_dev_account(
    session: AsyncSession,
    *,
    app_env: str,
    email: str,
    password: str,
    display_name: str,
    role: str,
    password_setting: str,
) -> User:
    if app_env != "development":
        raise RuntimeError("Development account seeding requires APP_ENV=development")
    if len(password) < 12:
        raise ValueError(f"{password_setting} must contain at least 12 characters")

    normalized_email = email.strip().lower()
    user = await session.scalar(select(User).where(User.email == normalized_email))
    if user is None:
        user = User(
            email=normalized_email,
            hashed_password=hash_password(password),
            display_name=display_name,
            role=role,
            status="active",
        )
        session.add(user)
    else:
        user.hashed_password = hash_password(password)
        user.role = role
        user.status = "active"
    await session.flush()
    return user
