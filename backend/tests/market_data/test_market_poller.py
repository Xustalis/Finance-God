"""Integration tests for the always-on market poller against SQLite."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from finance_god.application.market_poller import MarketPoller
from finance_god.infrastructure.persistence.market_monitor_models import (  # noqa: F401
    MarketAlertRow,
)
from finance_god.infrastructure.persistence.market_monitor_repository import (
    MarketMonitorUnitOfWork,
)
from finance_god.infrastructure.persistence.models import Base

NOW = datetime(2026, 7, 24, 9, 30, tzinfo=UTC)


def _quote(symbol: str, change_percent: str | None, *, last: str = "10.00") -> SimpleNamespace:
    return SimpleNamespace(
        symbol=symbol,
        name=f"Stock {symbol}",
        last=Decimal(last),
        change_percent=Decimal(change_percent) if change_percent is not None else None,
        provider_time="2026-07-24T09:30:00+08:00",
        frequency="1min",
        freshness="realtime",
        retrieved_at=NOW,
    )


class _FakeQuotes:
    """Return a scripted quote batch per poll cycle."""

    def __init__(self, batches: list[list[SimpleNamespace]]) -> None:
        self._batches = batches
        self.calls: list[list[str]] = []

    async def __call__(self, symbols: list[str]) -> SimpleNamespace:
        self.calls.append(list(symbols))
        index = min(len(self.calls) - 1, len(self._batches) - 1)
        return SimpleNamespace(quotes=list(self._batches[index]))


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def _poller(
    session_factory: async_sessionmaker[AsyncSession],
    quotes: _FakeQuotes,
) -> MarketPoller:
    ids = iter(f"market-alert-{n}" for n in range(1, 1000))
    return MarketPoller(
        quotes_provider=quotes,
        uow_factory=lambda: MarketMonitorUnitOfWork(session_factory),
        threshold=Decimal("0.05"),
        escalate_threshold=Decimal("0.09"),
        clock=lambda: NOW,
        ids=lambda: next(ids),
    )


@pytest.mark.asyncio
async def test_poll_once_persists_snapshot_and_records_crossing_alert(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    quotes = _FakeQuotes([[_quote("600519.SH", "0.061")]])
    poller = _poller(session_factory, quotes)

    created = await poller.poll_once(["600519.SH"])

    assert len(created) == 1
    assert created[0].symbol == "600519.SH"
    async with MarketMonitorUnitOfWork(session_factory) as uow:
        snapshots = await uow.monitor.list_snapshots()
        alerts = await uow.monitor.list_alerts()
    assert [s.symbol for s in snapshots] == ["600519.SH"]
    assert snapshots[0].change_percent == Decimal("0.061")
    assert [a.change_percent for a in alerts] == [Decimal("0.061")]


@pytest.mark.asyncio
async def test_poll_does_not_repeat_alert_while_move_persists(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    quotes = _FakeQuotes(
        [
            [_quote("600519.SH", "0.061")],
            [_quote("600519.SH", "0.070")],
        ]
    )
    poller = _poller(session_factory, quotes)

    first = await poller.poll_once(["600519.SH"])
    second = await poller.poll_once(["600519.SH"])

    assert len(first) == 1
    assert second == []
    async with MarketMonitorUnitOfWork(session_factory) as uow:
        alerts = await uow.monitor.list_alerts()
    assert len(alerts) == 1


@pytest.mark.asyncio
async def test_poll_skips_unpriceable_quotes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    quotes = _FakeQuotes(
        [[_quote("600519.SH", "0.061"), _quote("000001.SZ", None, last="0")]]
    )
    # A quote with no last price cannot be a baseline; it is skipped.
    quotes._batches[0][1] = SimpleNamespace(
        symbol="000001.SZ",
        name="No price",
        last=None,
        change_percent=Decimal("0.20"),
        provider_time="unknown",
        frequency="1min",
        freshness="stale",
        retrieved_at=NOW,
    )
    poller = _poller(session_factory, quotes)

    created = await poller.poll_once(["600519.SH", "000001.SZ"])

    assert [a.symbol for a in created] == ["600519.SH"]
    async with MarketMonitorUnitOfWork(session_factory) as uow:
        snapshots = await uow.monitor.list_snapshots()
    assert [s.symbol for s in snapshots] == ["600519.SH"]


@pytest.mark.asyncio
async def test_poll_notifies_strategy_observer_after_snapshot_is_persisted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    observed: list[str] = []

    async def observe(snapshot) -> None:
        async with MarketMonitorUnitOfWork(session_factory) as uow:
            persisted = await uow.monitor.get_snapshot(snapshot.symbol)
        assert persisted is not None
        observed.append(snapshot.symbol)

    poller = MarketPoller(
        quotes_provider=_FakeQuotes([[_quote("600519.SH", "0.01")]]),
        uow_factory=lambda: MarketMonitorUnitOfWork(session_factory),
        threshold=Decimal("0.05"),
        snapshot_observer=observe,
        clock=lambda: NOW,
    )

    await poller.poll_once(["600519.SH"])

    assert observed == ["600519.SH"]


@pytest.mark.asyncio
async def test_run_forever_stops_on_event_and_survives_provider_failure(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    class _Boom:
        def __init__(self) -> None:
            self.calls = 0

        async def __call__(self, symbols: list[str]) -> SimpleNamespace:
            self.calls += 1
            raise RuntimeError("upstream down")

    boom = _Boom()
    poller = MarketPoller(
        quotes_provider=boom,
        uow_factory=lambda: MarketMonitorUnitOfWork(session_factory),
        threshold=Decimal("0.05"),
        clock=lambda: NOW,
    )
    stop = asyncio.Event()

    async def stop_soon() -> None:
        await asyncio.sleep(0.02)
        stop.set()

    await asyncio.gather(
        poller.run_forever(symbols=["600519.SH"], interval_seconds=0.01, stop_event=stop),
        stop_soon(),
    )

    # The loop kept running through failures and then honored the stop event.
    assert boom.calls >= 1
