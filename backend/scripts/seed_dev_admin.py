"""Create or rotate the local development administrator account."""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import hash_password
from app.db.session import async_session_factory
from app.models.user import User


async def seed_dev_admin(
    session: AsyncSession,
    *,
    app_env: str,
    email: str,
    password: str,
) -> User:
    if app_env != "development":
        raise RuntimeError("Development administrator seeding requires APP_ENV=development")
    if len(password) < 12:
        raise ValueError("DEV_ADMIN_PASSWORD must contain at least 12 characters")

    normalized_email = email.strip().lower()
    user = await session.scalar(select(User).where(User.email == normalized_email))
    if user is None:
        user = User(
            email=normalized_email,
            hashed_password=hash_password(password),
            display_name="Development Administrator",
            role="admin",
            status="active",
        )
        session.add(user)
    else:
        user.hashed_password = hash_password(password)
        user.role = "admin"
        user.status = "active"
    await session.flush()
    return user


async def _run() -> None:
    if not settings.dev_admin_password:
        raise ValueError("DEV_ADMIN_PASSWORD must be configured")
    async with async_session_factory() as session:
        await seed_dev_admin(
            session,
            app_env=settings.app_env,
            email=settings.dev_admin_email,
            password=settings.dev_admin_password,
        )
        await session.commit()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
