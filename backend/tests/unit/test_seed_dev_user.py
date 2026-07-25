import pytest
from scripts.seed_dev_user import seed_dev_user
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import verify_password
from app.models.user import User


@pytest.mark.asyncio
async def test_seed_dev_user_is_development_only(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        with pytest.raises(RuntimeError, match="development"):
            await seed_dev_user(
                session,
                app_env="production",
                email="test@finance-god.local",
                password="strong-development-password",
            )


@pytest.mark.asyncio
async def test_seed_dev_user_requires_strong_password(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        with pytest.raises(ValueError, match="12 characters"):
            await seed_dev_user(
                session,
                app_env="development",
                email="test@finance-god.local",
                password="too-short",
            )


@pytest.mark.asyncio
async def test_seed_dev_user_is_idempotent_and_restores_user_role(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        first = await seed_dev_user(
            session,
            app_env="development",
            email="TEST@finance-god.local",
            password="first-development-password",
        )
        first.role = "admin"
        first.status = "inactive"
        second = await seed_dev_user(
            session,
            app_env="development",
            email="test@finance-god.local",
            password="second-development-password",
        )
        await session.commit()
        users = list(
            (await session.scalars(
                select(User).where(User.email == "test@finance-god.local")
            )).all()
        )

    assert first.id == second.id
    assert len(users) == 1
    assert users[0].role == "user"
    assert users[0].status == "active"
    assert verify_password("second-development-password", users[0].hashed_password)
