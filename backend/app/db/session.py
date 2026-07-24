"""统一数据库引擎、会话工厂与 FastAPI 会话依赖。"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from finance_god.infrastructure.persistence import create_session_factory

engine, async_session_factory = create_session_factory(
    settings.database_url,
    echo=settings.sql_echo,
    pool_size=10,
    max_overflow=20,
)

async def get_db() -> AsyncIterator[AsyncSession]:
    """依赖注入: 获取数据库会话"""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def create_db_session() -> AsyncSession:
    """为显式 Unit of Work 提供与 FastAPI 相同的会话工厂。"""
    return async_session_factory()


async def dispose_database() -> None:
    """释放统一连接池。"""
    await engine.dispose()
