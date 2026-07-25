from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from finance_god.infrastructure.simulation_wiring import MarketDataBarProvider
from finance_god.market_data import MarketBar


class _MarketData:
    def __init__(self, bars: tuple[MarketBar, ...]) -> None:
        self._bars = bars

    def read_historical_minute_bars(
        self,
        _symbol: str,
        *,
        trading_date: str,
        limit: int,
    ):
        assert trading_date == "20260724"
        assert limit == 500
        return SimpleNamespace(bars=self._bars, frequency="1分钟")


class _SimulationClock:
    def __init__(self, current_time: datetime) -> None:
        self._current_time = current_time

    async def get_for_account(self, account_id: str):
        assert account_id == "account-1"
        return SimpleNamespace(current_time=self._current_time, revision=3)


def _bar(timestamp: datetime, *, freshness: str = "current") -> MarketBar:
    rendered = timestamp.isoformat()
    return MarketBar(
        time=rendered,
        open="11.10",
        high="11.20",
        low="11.00",
        close="11.15",
        volume="10000",
        freshness=freshness,
        provider_time=rendered,
        source_endpoint="get_stock_min",
        capability_version="pandadata-capabilities-v1",
        instrument_master_identity="finance-god-instrument-master",
        instrument_master_version="master-v1",
    )


def test_provider_selects_the_first_real_bar_after_submission() -> None:
    submitted_at = datetime(2026, 7, 24, 2, 0, tzinfo=UTC)
    before = _bar(submitted_at - timedelta(minutes=1))
    first_after = _bar(submitted_at + timedelta(minutes=1))
    later = _bar(submitted_at + timedelta(minutes=2))
    provider = MarketDataBarProvider(
        _MarketData((before, later, first_after)),
        _SimulationClock(submitted_at + timedelta(minutes=2)),
    )
    draft = SimpleNamespace(
        account_id="account-1",
        instrument_id="000001.SZ",
        audit_reference=SimpleNamespace(recorded_at=submitted_at),
    )

    result = asyncio.run(provider.next_bar(draft, submitted_at=submitted_at))

    assert result is not None
    assert result.upstream_timestamp == submitted_at + timedelta(minutes=1)
    assert result.open == first_after.open
    assert result.evidence.version == f"{first_after.provider_time}:clock:3"


def test_provider_does_not_invent_staleness_for_unknown_upstream_freshness() -> None:
    submitted_at = datetime(2026, 7, 24, 2, 0, tzinfo=UTC)
    provider = MarketDataBarProvider(
        _MarketData((_bar(submitted_at + timedelta(minutes=1), freshness="unknown"),)),
        _SimulationClock(submitted_at + timedelta(minutes=2)),
    )
    draft = SimpleNamespace(
        account_id="account-1",
        instrument_id="000001.SZ",
        audit_reference=SimpleNamespace(recorded_at=submitted_at),
    )

    result = asyncio.run(provider.next_bar(draft, submitted_at=submitted_at))

    assert result is not None
    assert result.stale is False


def test_provider_returns_none_until_a_post_submission_bar_exists() -> None:
    submitted_at = datetime(2026, 7, 24, 2, 0, tzinfo=UTC)
    provider = MarketDataBarProvider(
        _MarketData((_bar(submitted_at - timedelta(minutes=1)),)),
        _SimulationClock(submitted_at + timedelta(minutes=2)),
    )
    draft = SimpleNamespace(
        account_id="account-1",
        instrument_id="000001.SZ",
        audit_reference=SimpleNamespace(recorded_at=submitted_at),
    )

    assert asyncio.run(provider.next_bar(draft, submitted_at=submitted_at)) is None
