from __future__ import annotations

from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession, AsyncSessionTransaction

from bridge.persistence.database import SessionFactory
from bridge.persistence.repository import BridgeRepository


class AsyncUnitOfWork:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._transaction: AsyncSessionTransaction | None = None
        self.repository: BridgeRepository | None = None

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("unit of work has not been entered")
        return self._session

    async def __aenter__(self) -> AsyncUnitOfWork:
        if self._session is not None:
            raise RuntimeError("unit of work cannot be entered more than once")
        self._session = self._session_factory()
        self._transaction = await self._session.begin()
        self.repository = BridgeRepository(self._session)
        return self

    async def commit(self) -> None:
        if self._transaction is None:
            raise RuntimeError("unit of work has not been entered")
        await self._transaction.commit()
        self._transaction = None

    async def rollback(self) -> None:
        if self._transaction is not None:
            await self._transaction.rollback()
            self._transaction = None

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_value, traceback
        if exc_type is not None or self._transaction is not None:
            await self.rollback()
        if self._session is not None:
            await self._session.close()
        self._session = None
        self.repository = None
