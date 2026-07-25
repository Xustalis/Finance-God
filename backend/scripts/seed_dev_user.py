"""Create or rotate the local development test user account."""

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import async_session_factory
from app.models.user import User
from scripts.dev_account_seed import seed_dev_account


async def seed_dev_user(
    session: AsyncSession,
    *,
    app_env: str,
    email: str,
    password: str,
) -> User:
    return await seed_dev_account(
        session,
        app_env=app_env,
        email=email,
        password=password,
        display_name="Development Test User",
        role="user",
        password_setting="DEV_TEST_USER_PASSWORD",
    )


async def _run() -> None:
    if not settings.dev_test_user_password:
        raise ValueError("DEV_TEST_USER_PASSWORD must be configured")
    async with async_session_factory() as session:
        await seed_dev_user(
            session,
            app_env=settings.app_env,
            email=settings.dev_test_user_email,
            password=settings.dev_test_user_password,
        )
        await session.commit()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
