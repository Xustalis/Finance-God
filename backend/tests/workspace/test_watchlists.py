from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from finance_god.domain.errors import ConcurrentCommandConflict, DomainInvariantViolation
from finance_god.domain.models import WatchlistGroup
from finance_god.infrastructure.persistence.models import Base
from finance_god.infrastructure.persistence.workspace_uow import WorkspaceUnitOfWork


def _group(group_id: str, owner_user_id: str = "test-user") -> WatchlistGroup:
    now = datetime.now(UTC)
    return WatchlistGroup(
        group_id=group_id,
        owner_user_id=owner_user_id,
        name="My Group",
        description=None,
        revision=1,
        created_at=now,
        updated_at=now,
    )


def test_watchlist_crud(tmp_path) -> None:
    asyncio.run(_test_watchlist_crud(tmp_path / "workspace.db"))


async def _test_watchlist_crud(database) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{database}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with WorkspaceUnitOfWork(session_factory) as uow:
        created = await uow.watchlists.create_group(_group("g1"))
        await uow.commit()
    assert created.group_id == "g1"

    async with WorkspaceUnitOfWork(session_factory) as uow:
        retrieved = await uow.watchlists.get_group("test-user", "g1")
        assert retrieved is not None
        updated = await uow.watchlists.update_group(
            retrieved.model_copy(update={"name": "Updated"}), expected_revision=1
        )
        instrument = await uow.watchlists.add_instrument(
            owner_user_id="test-user",
            group_id="g1",
            instrument_id="000001.SZ",
            added_by="test-user",
        )
        await uow.commit()
    assert updated.revision == 2
    assert instrument.group_id == "g1"

    async with WorkspaceUnitOfWork(session_factory) as uow:
        groups = await uow.watchlists.list_groups("test-user")
    assert [group.name for group in groups] == ["Updated"]
    await engine.dispose()


def test_revision_conflict_and_owner_boundary(tmp_path) -> None:
    asyncio.run(_test_revision_conflict_and_owner_boundary(tmp_path / "workspace.db"))


async def _test_revision_conflict_and_owner_boundary(database) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{database}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with WorkspaceUnitOfWork(session_factory) as uow:
        group = await uow.watchlists.create_group(_group("g2"))
        await uow.commit()

    async with WorkspaceUnitOfWork(session_factory) as uow:
        with pytest.raises(ConcurrentCommandConflict):
            await uow.watchlists.update_group(group, expected_revision=2)
        with pytest.raises(DomainInvariantViolation):
            await uow.watchlists.add_instrument(
                owner_user_id="another-user",
                group_id="g2",
                instrument_id="000001.SZ",
                added_by="another-user",
            )
    await engine.dispose()
