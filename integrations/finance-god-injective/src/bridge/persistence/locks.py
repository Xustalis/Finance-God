from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from hashlib import blake2b

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class UnsupportedAdvisoryLockError(RuntimeError):
    pass


def advisory_lock_id(lock_key: str) -> int:
    digest = blake2b(lock_key.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, byteorder="big", signed=True)


@asynccontextmanager
async def wallet_advisory_lock(
    session: AsyncSession,
    lock_key: str,
    *,
    allow_sqlite_test_noop: bool = False,
) -> AsyncIterator[None]:
    if not lock_key:
        raise ValueError("lock_key cannot be blank")
    if not session.in_transaction():
        raise RuntimeError("wallet advisory locks require an active transaction")

    bind = session.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": advisory_lock_id(lock_key)},
        )
        yield
        return
    if dialect == "sqlite" and allow_sqlite_test_noop:
        yield
        return
    raise UnsupportedAdvisoryLockError(
        f"wallet advisory locks are unsupported for dialect {dialect!r}; "
        "the SQLite no-op must be enabled explicitly by tests"
    )
