from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def reset_public_schema(database_url: str) -> None:
    """Reset every migration-owned object in a dedicated PostgreSQL test database."""
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
    finally:
        await engine.dispose()
