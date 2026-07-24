from __future__ import annotations

from collections.abc import Callable
from types import TracebackType
from typing import Self

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .simulation_repository import SimulationRepository


class SimulationUnitOfWork:
    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> Self:
        self._session = self._session_factory()
        if self._session.get_bind().dialect.name == "sqlite":
            await self._session.execute(text("BEGIN IMMEDIATE"))
            transaction = self._session.get_transaction()
            if transaction is None:
                raise RuntimeError("SQLite simulation transaction did not start")
            self._transaction = transaction
        else:
            self._transaction = await self._session.begin()
        self.repository = SimulationRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc, traceback
        if self._transaction.is_active:
            await self._transaction.rollback()
        assert self._session is not None
        await self._session.close()
        self._session = None

    async def commit(self) -> None:
        await self._transaction.commit()
