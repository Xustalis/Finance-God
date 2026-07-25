from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from finance_god.infrastructure.persistence.models import AccountRow, SimulationClockRow

SHANGHAI = ZoneInfo("Asia/Shanghai")
MORNING_OPEN = time(9, 30)
MORNING_CLOSE = time(11, 30)
AFTERNOON_OPEN = time(13, 0)
AFTERNOON_CLOSE = time(15, 0)


class SimulationClockView(BaseModel):
    model_config = ConfigDict(frozen=True)

    account_id: str
    current_time: AwareDatetime
    speed: Literal[1] = 1
    status: Literal["running", "paused_market_closed"]
    session_close_at: AwareDatetime
    next_session_open_at: AwareDatetime
    revision: int


class SimulationClockService:
    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
        *,
        wall_clock: Callable[[], datetime] | None = None,
        next_session_resolver: Callable[[datetime], Awaitable[datetime]] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._wall_clock = wall_clock or (lambda: datetime.now(UTC))
        self._next_session_resolver = next_session_resolver

    async def create(self, account_id: str, start_at: datetime) -> SimulationClockView:
        normalized = _require_trading_minute(start_at)
        now = _aware_utc(self._wall_clock())
        async with self._session_factory() as session, session.begin():
            session.add(
                SimulationClockRow(
                    account_id=account_id,
                    simulation_start_at=normalized,
                    real_anchor_at=now,
                    status="running",
                    paused_at=None,
                    timezone="Asia/Shanghai",
                    speed=1,
                    revision=1,
                    last_resume_key=None,
                )
            )
        return await self.get_for_account(account_id)

    async def current_for_owner(self, owner_id: str) -> SimulationClockView:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(SimulationClockRow)
                .join(AccountRow, AccountRow.account_id == SimulationClockRow.account_id)
                .where(AccountRow.owner_user_id == owner_id, AccountRow.current.is_(True))
            )
        if row is None:
            raise LookupError("simulation clock not found")
        return await self._materialize(row)

    async def get_for_account(self, account_id: str) -> SimulationClockView:
        current = await self.find_for_account(account_id)
        if current is None:
            raise LookupError("simulation clock not found")
        return current

    async def find_for_account(
        self, account_id: str
    ) -> SimulationClockView | None:
        async with self._session_factory() as session:
            row = await session.get(SimulationClockRow, account_id)
        if row is None:
            return None
        return await self._materialize(row)

    async def resume_next_session(
        self,
        owner_id: str,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> SimulationClockView:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(SimulationClockRow)
                .join(AccountRow, AccountRow.account_id == SimulationClockRow.account_id)
                .where(AccountRow.owner_user_id == owner_id, AccountRow.current.is_(True))
            )
        if row is None:
            raise LookupError("simulation clock not found")
        if row.last_resume_key == idempotency_key:
            return await self.get_for_account(row.account_id)
        current = await self._materialize(row)
        if current.status != "paused_market_closed":
            raise ValueError("simulation clock is not paused at market close")
        if current.revision != expected_revision:
            raise ValueError("simulation clock revision changed")
        next_open = current.next_session_open_at
        now = _aware_utc(self._wall_clock())
        async with self._session_factory() as session, session.begin():
            result = await session.execute(
                update(SimulationClockRow)
                .where(
                    SimulationClockRow.account_id == current.account_id,
                    SimulationClockRow.revision == expected_revision,
                )
                .values(
                    simulation_start_at=next_open,
                    real_anchor_at=now,
                    status="running",
                    paused_at=None,
                    revision=expected_revision + 1,
                    last_resume_key=idempotency_key,
                )
            )
            if result.rowcount != 1:
                raise ValueError("simulation clock revision changed")
        return await self.get_for_account(current.account_id)

    async def _materialize(self, row: SimulationClockRow) -> SimulationClockView:
        now = _aware_utc(self._wall_clock())
        start = _aware_utc(row.simulation_start_at)
        candidate = start if row.status == "paused_market_closed" else start + (now - row.real_anchor_at)
        close_at = (
            start
            if row.status == "paused_market_closed"
            else _session_close(start)
        )
        if candidate >= close_at and row.status == "running":
            candidate = close_at
            async with self._session_factory() as session, session.begin():
                await session.execute(
                    update(SimulationClockRow)
                    .where(
                        SimulationClockRow.account_id == row.account_id,
                        SimulationClockRow.revision == row.revision,
                    )
                    .values(
                        simulation_start_at=candidate,
                        real_anchor_at=now,
                        status="paused_market_closed",
                        paused_at=candidate,
                        revision=row.revision + 1,
                    )
                )
            return await self.get_for_account(row.account_id)
        next_open = _next_session_open(close_at)
        if row.status == "paused_market_closed" and self._next_session_resolver:
            next_open = _aware_utc(await self._next_session_resolver(close_at))
        return SimulationClockView(
            account_id=row.account_id,
            current_time=candidate,
            status=row.status,
            session_close_at=close_at,
            next_session_open_at=next_open,
            revision=row.revision,
        )


def _require_trading_minute(value: datetime) -> datetime:
    local = _aware_utc(value).astimezone(SHANGHAI)
    if local.second or local.microsecond:
        raise ValueError("simulation_start_at must be aligned to a minute")
    if local.weekday() >= 5:
        raise ValueError("simulation_start_at must be an A-share trading minute")
    clock = local.timetz().replace(tzinfo=None)
    if not (MORNING_OPEN <= clock < MORNING_CLOSE or AFTERNOON_OPEN <= clock < AFTERNOON_CLOSE):
        raise ValueError("simulation_start_at must be inside an A-share trading session")
    return local.astimezone(UTC)


def _session_close(value: datetime) -> datetime:
    local = _aware_utc(value).astimezone(SHANGHAI)
    clock = local.timetz().replace(tzinfo=None)
    close = MORNING_CLOSE if clock < MORNING_CLOSE else AFTERNOON_CLOSE
    return datetime.combine(local.date(), close, SHANGHAI).astimezone(UTC)


def _next_session_open(value: datetime) -> datetime:
    local = _aware_utc(value).astimezone(SHANGHAI)
    clock = local.timetz().replace(tzinfo=None)
    if clock <= MORNING_CLOSE:
        return datetime.combine(local.date(), AFTERNOON_OPEN, SHANGHAI).astimezone(UTC)
    day = local.date() + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return datetime.combine(day, MORNING_OPEN, SHANGHAI).astimezone(UTC)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock values must be timezone-aware")
    return value.astimezone(UTC)
