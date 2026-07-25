from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from finance_god.application.simulation_clock import SimulationClockService
from finance_god.infrastructure.persistence.models import (
    AccountRow,
    Base,
)


@pytest.mark.asyncio
async def test_find_clock_returns_none_for_account_created_before_clock_migration() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    service = SimulationClockService(sessions)

    assert await service.find_for_account("legacy-account") is None
    with pytest.raises(LookupError, match="simulation clock not found"):
        await service.get_for_account("legacy-account")
    await engine.dispose()


@pytest.mark.asyncio
async def test_clock_advances_one_to_one_and_pauses_at_lunch() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    wall = [datetime(2026, 7, 24, 1, 0, tzinfo=UTC)]
    async with sessions() as session, session.begin():
        session.add(
            AccountRow(
                account_id="account-1",
                owner_user_id="owner-1",
                initial_cash_rmb=100_000,
                status="active",
                current=True,
                revision=1,
                created_at=wall[0],
                closed_at=None,
                reset_from_account_id=None,
            )
        )
    service = SimulationClockService(sessions, wall_clock=lambda: wall[0])
    await service.create("account-1", datetime(2026, 7, 24, 3, 29, tzinfo=UTC))

    wall[0] = datetime(2026, 7, 24, 1, 0, 30, tzinfo=UTC)
    running = await service.current_for_owner("owner-1")
    assert running.current_time == datetime(2026, 7, 24, 3, 29, 30, tzinfo=UTC)
    assert running.status == "running"

    wall[0] = datetime(2026, 7, 24, 1, 2, tzinfo=UTC)
    paused = await service.current_for_owner("owner-1")
    assert paused.current_time == datetime(2026, 7, 24, 3, 30, tzinfo=UTC)
    assert paused.status == "paused_market_closed"
    assert paused.next_session_open_at == datetime(2026, 7, 24, 5, 0, tzinfo=UTC)
    await engine.dispose()


@pytest.mark.asyncio
async def test_clock_resume_requires_revision_and_moves_to_next_session() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    wall = [datetime(2026, 7, 24, 1, 0, tzinfo=UTC)]
    async with sessions() as session, session.begin():
        session.add(
            AccountRow(
                account_id="account-1",
                owner_user_id="owner-1",
                initial_cash_rmb=100_000,
                status="active",
                current=True,
                revision=1,
                created_at=wall[0],
                closed_at=None,
                reset_from_account_id=None,
            )
        )
    service = SimulationClockService(sessions, wall_clock=lambda: wall[0])
    await service.create("account-1", datetime(2026, 7, 24, 3, 29, tzinfo=UTC))
    wall[0] = datetime(2026, 7, 24, 1, 2, tzinfo=UTC)
    paused = await service.current_for_owner("owner-1")

    with pytest.raises(ValueError, match="revision"):
        await service.resume_next_session(
            "owner-1",
            expected_revision=paused.revision - 1,
            idempotency_key="resume-1",
        )
    resumed = await service.resume_next_session(
        "owner-1",
        expected_revision=paused.revision,
        idempotency_key="resume-1",
    )
    assert resumed.status == "running"
    assert resumed.current_time == datetime(2026, 7, 24, 5, 0, tzinfo=UTC)
    replay = await service.resume_next_session(
        "owner-1",
        expected_revision=paused.revision,
        idempotency_key="resume-1",
    )
    assert replay == resumed
    await engine.dispose()


@pytest.mark.asyncio
async def test_clock_rejects_non_trading_minutes() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    service = SimulationClockService(sessions)
    with pytest.raises(ValueError, match="trading"):
        await service.create(
            "missing-account",
            datetime(2026, 7, 25, 1, 30, tzinfo=UTC),
        )
    await engine.dispose()
