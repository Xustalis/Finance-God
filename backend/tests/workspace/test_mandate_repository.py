from __future__ import annotations

import asyncio
import itertools
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from finance_god.application.mandate_service import MandateService, MandateSpec
from finance_god.domain.errors import ConcurrentCommandConflict
from finance_god.infrastructure.persistence.models import Base
from finance_god.trading.access import AuthorizationStatus, AutonomyLevel
from finance_god.trading.mandate import DEFAULT_LIMITS

NOW = datetime(2026, 7, 24, 8, tzinfo=UTC)


class _Clock:
    def now(self) -> datetime:
        return NOW


class _IDs:
    def __init__(self) -> None:
        self._counter = itertools.count(1)

    def new_id(self, prefix: str) -> str:
        return f"{prefix}-{next(self._counter)}"


def _spec(**overrides: object) -> MandateSpec:
    base = dict(
        autonomy_level=AutonomyLevel.L1,
        allowed_markets=("CN", "HK"),
        allowed_assets=("stock", "etf"),
        allowed_sides=("buy", "sell"),
        allowed_order_types=("limit", "market"),
        short_markets=(),
        limits=DEFAULT_LIMITS,
        valid_until=NOW + timedelta(days=90),
        note="tightened",
    )
    base.update(overrides)
    return MandateSpec(**base)  # type: ignore[arg-type]


async def _service(tmp_path) -> MandateService:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'mandate.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return MandateService(session_factory=factory, clock=_Clock(), ids=_IDs())


def test_ensure_current_auto_creates_default(tmp_path) -> None:
    async def run() -> None:
        service = await _service(tmp_path)
        current = await service.ensure_current("owner-1")
        assert current.version == 1
        assert current.status is AuthorizationStatus.ACTIVE
        assert current.autonomy_level is AutonomyLevel.L0
        # Idempotent: a second read returns the same version, not a new one.
        again = await service.ensure_current("owner-1")
        assert again.version == 1
        assert len(await service.history("owner-1")) == 1

    asyncio.run(run())


def test_save_version_appends_and_current_is_max(tmp_path) -> None:
    async def run() -> None:
        service = await _service(tmp_path)
        await service.ensure_current("owner-1")
        saved = await service.save_version(
            "owner-1", expected_revision=1, spec=_spec()
        )
        assert saved.version == 2
        assert saved.autonomy_level is AutonomyLevel.L1
        history = await service.history("owner-1")
        assert [m.version for m in history] == [2, 1]  # descending, history kept

    asyncio.run(run())


def test_save_version_rejects_stale_revision(tmp_path) -> None:
    async def run() -> None:
        service = await _service(tmp_path)
        await service.ensure_current("owner-1")
        await service.save_version("owner-1", expected_revision=1, spec=_spec())
        with pytest.raises(ConcurrentCommandConflict):
            await service.save_version("owner-1", expected_revision=1, spec=_spec())

    asyncio.run(run())


def test_set_status_appends_version_without_overwriting_history(tmp_path) -> None:
    async def run() -> None:
        service = await _service(tmp_path)
        await service.ensure_current("owner-1")
        paused = await service.set_status(
            "owner-1", expected_revision=1, status=AuthorizationStatus.PAUSED
        )
        assert paused.version == 2
        assert paused.status is AuthorizationStatus.PAUSED
        resumed = await service.set_status(
            "owner-1", expected_revision=2, status=AuthorizationStatus.ACTIVE
        )
        assert resumed.version == 3
        assert resumed.status is AuthorizationStatus.ACTIVE
        history = await service.history("owner-1")
        assert [m.status for m in history] == [
            AuthorizationStatus.ACTIVE,
            AuthorizationStatus.PAUSED,
            AuthorizationStatus.ACTIVE,
        ]

    asyncio.run(run())


def test_owner_isolation(tmp_path) -> None:
    async def run() -> None:
        service = await _service(tmp_path)
        await service.ensure_current("owner-1")
        await service.save_version("owner-1", expected_revision=1, spec=_spec())
        other = await service.ensure_current("owner-2")
        assert other.version == 1
        assert len(await service.history("owner-2")) == 1

    asyncio.run(run())
