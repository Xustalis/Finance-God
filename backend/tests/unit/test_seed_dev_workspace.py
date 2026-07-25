from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from scripts.seed_dev_workspace import seed_dev_workspace
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base as AppBase
from app.models.user import User
from finance_god.application.ledger_service import (
    CreateAccountCommand,
    SimulationLedgerService,
)
from finance_god.domain import VersionReference
from finance_god.domain.simulation_rules import SIMULATION_RULE_VERSION
from finance_god.infrastructure.persistence import Base as TradingBase
from finance_god.infrastructure.persistence import SqlAlchemyUnitOfWork
from finance_god.infrastructure.persistence.simulation_models import (
    SimulationFillRow,
    SimulationOrderRow,
)
from finance_god.infrastructure.persistence.trade_review_models import TradeEpisodeRow
from finance_god.infrastructure.persistence.workspace_models import (
    WatchlistGroupRow,
    WatchlistInstrumentRow,
)
from finance_god.infrastructure.simulation_wiring import SystemClock, UuidIdGenerator

EMAIL = "test@finance-god.local"


class _Rules:
    simulation_rule_version = SIMULATION_RULE_VERSION


@pytest.fixture
async def workspace_sessions() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(AppBase.metadata.create_all)
        await connection.run_sync(TradingBase.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    yield sessions
    await engine.dispose()


async def _add_user(sessions: async_sessionmaker[AsyncSession]) -> User:
    async with sessions() as session:
        user = User(
            email=EMAIL,
            hashed_password="not-used-by-workspace-seed",
            display_name="Development Test User",
        )
        session.add(user)
        await session.commit()
        return user


@pytest.mark.asyncio
async def test_workspace_seed_is_development_only(
    workspace_sessions: async_sessionmaker[AsyncSession],
) -> None:
    with pytest.raises(RuntimeError, match="development"):
        await seed_dev_workspace(
            workspace_sessions,
            app_env="production",
            email=EMAIL,
        )


@pytest.mark.asyncio
async def test_workspace_seed_requires_existing_test_user(
    workspace_sessions: async_sessionmaker[AsyncSession],
) -> None:
    with pytest.raises(LookupError, match="seed-dev-user"):
        await seed_dev_workspace(
            workspace_sessions,
            app_env="development",
            email=EMAIL,
        )


@pytest.mark.asyncio
async def test_workspace_seed_creates_consistent_data_and_is_idempotent(
    workspace_sessions: async_sessionmaker[AsyncSession],
) -> None:
    await _add_user(workspace_sessions)

    first = await seed_dev_workspace(
        workspace_sessions,
        app_env="development",
        email=EMAIL,
    )
    second = await seed_dev_workspace(
        workspace_sessions,
        app_env="development",
        email=EMAIL,
    )

    assert first["account_id"] == second["account_id"]
    async with workspace_sessions() as session:
        order_count = await session.scalar(
            select(func.count()).select_from(SimulationOrderRow)
        )
        fill_count = await session.scalar(
            select(func.count()).select_from(SimulationFillRow)
        )
        episode_count = await session.scalar(
            select(func.count()).select_from(TradeEpisodeRow)
        )
        group_count = await session.scalar(
            select(func.count()).select_from(WatchlistGroupRow)
        )
        instrument_count = await session.scalar(
            select(func.count()).select_from(WatchlistInstrumentRow)
        )
        episodes = list((await session.scalars(select(TradeEpisodeRow))).all())

    assert order_count == 3
    assert fill_count == 3
    assert episode_count == 2
    assert group_count == 2
    assert instrument_count == 3
    assert {row.status for row in episodes} == {"open", "review_completed"}
    assert second["watchlist_groups"] == 0
    assert second["watchlist_instruments"] == 0


@pytest.mark.asyncio
async def test_workspace_seed_does_not_top_up_an_underfunded_existing_account(
    workspace_sessions: async_sessionmaker[AsyncSession],
) -> None:
    user = await _add_user(workspace_sessions)
    ledger = SimulationLedgerService(
        uow_factory=lambda: SqlAlchemyUnitOfWork(workspace_sessions),
        clock=SystemClock(),
        ids=UuidIdGenerator(),
        rules=_Rules(),
    )
    await ledger.create_account(
        CreateAccountCommand(
            owner_user_id=str(user.id),
            idempotency_key="underfunded-account",
            correlation_id="underfunded-correlation",
            causation_id="underfunded-causation",
            source=VersionReference(
                object_type="test",
                object_id="underfunded-account",
                version="1",
            ),
            initial_cash_rmb=Decimal("100"),
            business_time=datetime.now(UTC),
        )
    )

    with pytest.raises(Exception, match="insufficient available cash"):
        await seed_dev_workspace(
            workspace_sessions,
            app_env="development",
            email=EMAIL,
        )
