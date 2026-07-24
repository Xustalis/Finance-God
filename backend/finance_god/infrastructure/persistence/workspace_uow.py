from __future__ import annotations

from collections.abc import Callable
from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession

from .workspace_repository import (
    NotificationPreferenceRepository,
    NotificationRepository,
    WatchlistRepository,
)


class WorkspaceUnitOfWork:
    """One database transaction and repository set for a workspace request."""

    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> Self:
        if self._session is not None:
            raise RuntimeError("workspace unit of work is already active")
        self._session = self._session_factory()
        self._transaction = await self._session.begin()
        self.watchlists = WatchlistRepository(self._session)
        self.notifications = NotificationRepository(self._session)
        self.preferences = NotificationPreferenceRepository(self._session)
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

    async def flush(self) -> None:
        session = self._require_session()
        await session.flush()

    def get_watchlist_repo(self) -> WatchlistRepository:
        self._require_session()
        return self.watchlists

    def get_notification_repo(self) -> NotificationRepository:
        self._require_session()
        return self.notifications

    def get_preference_repo(self) -> NotificationPreferenceRepository:
        self._require_session()
        return self.preferences

    def _require_session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("workspace unit of work is not active")
        return self._session
