from __future__ import annotations

from collections.abc import Callable
from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession

from .trade_plan_repository import TradePlanRepository


class TradePlanUnitOfWork:
    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> Self:
        if self._session is not None:
            raise RuntimeError("trade plan unit of work is already active")
        self._session = self._session_factory()
        self._transaction = await self._session.begin()
        self.plans = TradePlanRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        if self._transaction.is_active:
            await self._transaction.rollback()
        assert self._session is not None
        await self._session.close()
        self._session = None

    async def commit(self) -> None:
        await self._transaction.commit()
