from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AccountRow


class AggregateLocks:
    """Serialize commands that mutate the same owner or account."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def owner(self, owner_user_id: str) -> None:
        if self._session.bind and self._session.bind.dialect.name == "postgresql":
            await self._session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"owner:{owner_user_id}"},
            )

    async def account(self, account_id: str) -> None:
        row = await self._session.scalar(
            select(AccountRow.account_id)
            .where(AccountRow.account_id == account_id)
            .with_for_update()
        )
        if row is None:
            return
