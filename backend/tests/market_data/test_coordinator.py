from __future__ import annotations

import asyncio
from threading import Event, Lock

from finance_god.market_data import (
    DataEnvelope,
    ErrorKind,
    MarketDataError,
    RefreshState,
    SnapshotCoordinator,
)
from finance_god.market_data.contracts import (
    InstrumentId,
    NormalizedSnapshot,
    ReleaseState,
)
from finance_god.market_data.freshness import FreshnessPolicy
from finance_god.market_data.instruments import DEFAULT_INSTRUMENT_MASTER
from finance_god.market_data.normalization import PandaDataNormalizer

from .conftest import NOW, stock_snapshot


def _success(instrument: InstrumentId) -> DataEnvelope[NormalizedSnapshot]:
    result = PandaDataNormalizer(FreshnessPolicy()).snapshot(
        [stock_snapshot(instrument.provider_symbol)],
        instrument=instrument,
        endpoint="get_stock_rt_daily",
        ingested_at=NOW,
        release_state=ReleaseState.RELEASED,
        expected_date="20260723",
    )
    return result


def test_same_symbol_and_overlapping_batches_use_one_singleflight() -> None:
    asyncio.run(_same_symbol_and_overlapping_batches_use_one_singleflight())


async def _same_symbol_and_overlapping_batches_use_one_singleflight() -> None:
    counts: dict[str, int] = {}
    lock = Lock()
    entered = Event()
    release = Event()

    def fetcher(
        instrument: InstrumentId,
    ) -> DataEnvelope[NormalizedSnapshot]:
        with lock:
            counts[instrument.symbol] = counts.get(instrument.symbol, 0) + 1
            if sum(counts.values()) >= 2:
                entered.set()
        release.wait(timeout=2)
        return _success(instrument)

    coordinator = SnapshotCoordinator(fetcher)
    a = DEFAULT_INSTRUMENT_MASTER.resolve("000001.SZ")
    b = DEFAULT_INSTRUMENT_MASTER.resolve("600519.SH")

    first = asyncio.create_task(coordinator.get([a, b]))
    second = asyncio.create_task(coordinator.get([b]))
    assert await asyncio.to_thread(entered.wait, 1)
    release.set()
    first_result, second_result = await asyncio.gather(first, second)

    assert counts == {"000001.SZ": 1, "600519.SH": 1}
    assert second_result.items == (first_result.items[1],)


def test_different_symbols_refresh_concurrently_without_global_network_lock() -> None:
    asyncio.run(_different_symbols_refresh_concurrently_without_global_network_lock())


async def _different_symbols_refresh_concurrently_without_global_network_lock() -> None:
    entered: set[str] = set()
    lock = Lock()
    both = Event()
    release = Event()

    def fetcher(
        instrument: InstrumentId,
    ) -> DataEnvelope[NormalizedSnapshot]:
        with lock:
            entered.add(instrument.symbol)
            if len(entered) == 2:
                both.set()
        release.wait(timeout=2)
        return _success(instrument)

    coordinator = SnapshotCoordinator(fetcher)
    request = [
        DEFAULT_INSTRUMENT_MASTER.resolve("000001.SZ"),
        DEFAULT_INSTRUMENT_MASTER.resolve("600519.SH"),
    ]
    task = asyncio.create_task(coordinator.get(request))
    assert await asyncio.to_thread(both.wait, 1)
    release.set()
    await task
    assert entered == {"000001.SZ", "600519.SH"}


def test_background_refresh_failure_is_visible_and_old_value_is_stale() -> None:
    asyncio.run(_background_refresh_failure_is_visible_and_old_value_is_stale())


async def _background_refresh_failure_is_visible_and_old_value_is_stale() -> None:
    tick = 100.0
    attempts = 0

    def clock() -> float:
        return tick

    def fetcher(
        instrument: InstrumentId,
    ) -> DataEnvelope[NormalizedSnapshot]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return _success(instrument)
        raise MarketDataError(
            ErrorKind.PERMISSION,
            "permission denied",
            endpoint="get_stock_rt_daily",
        )

    coordinator = SnapshotCoordinator(
        fetcher,
        refresh_after_seconds=0.9,
        max_transient_retries=0,
        clock=clock,
    )
    instrument = DEFAULT_INSTRUMENT_MASTER.resolve("000001.SZ")
    first = await coordinator.get([instrument])
    tick += 1
    pending = await coordinator.get([instrument])
    await coordinator.wait_for_refreshes()
    failed = await coordinator.get([instrument])
    state = await coordinator.cache_state(instrument.symbol)

    assert first.items[0].freshness.status.value == "current"
    assert pending.items[0].freshness.status.value == "stale"
    assert failed.items[0].freshness.status.value == "stale"
    assert failed.diagnostics[0].code.value == "refresh_failed"
    assert state is not None
    assert state.refresh_state is RefreshState.ERROR
    assert state.last_success
    assert state.latest_diagnostic is not None


def test_coordinator_does_not_stack_retries_over_transport() -> None:
    asyncio.run(_coordinator_does_not_stack_retries_over_transport())


async def _coordinator_does_not_stack_retries_over_transport() -> None:
    instrument = DEFAULT_INSTRUMENT_MASTER.resolve("000001.SZ")
    transient_attempts = 0

    def transient(instrument: InstrumentId) -> DataEnvelope[NormalizedSnapshot]:
        del instrument
        nonlocal transient_attempts
        transient_attempts += 1
        raise MarketDataError(
            ErrorKind.TRANSIENT, "timeout", endpoint="get_stock_rt_daily"
        )

    transient_coordinator = SnapshotCoordinator(
        transient,
        max_transient_retries=0,
    )
    result = await transient_coordinator.get([instrument])
    assert transient_attempts == 1
    assert result.diagnostics[0].retryable is True

    permission_attempts = 0

    def permission(instrument: InstrumentId) -> DataEnvelope[NormalizedSnapshot]:
        del instrument
        nonlocal permission_attempts
        permission_attempts += 1
        raise MarketDataError(
            ErrorKind.PERMISSION, "denied", endpoint="get_stock_rt_daily"
        )

    permission_coordinator = SnapshotCoordinator(
        permission,
        max_transient_retries=0,
    )
    denied = await permission_coordinator.get([instrument])
    assert permission_attempts == 1
    assert denied.diagnostics[0].retryable is False


def test_unexpected_exception_becomes_visible_error_state() -> None:
    asyncio.run(_unexpected_exception_becomes_visible_error_state())


async def _unexpected_exception_becomes_visible_error_state() -> None:
    instrument = DEFAULT_INSTRUMENT_MASTER.resolve("000001.SZ")

    def broken(instrument: InstrumentId) -> DataEnvelope[NormalizedSnapshot]:
        del instrument
        raise RuntimeError("secret implementation detail")

    coordinator = SnapshotCoordinator(broken)
    result = await coordinator.get([instrument])
    state = await coordinator.cache_state(instrument.symbol)

    assert result.items == ()
    assert result.diagnostics[0].code.value == "unexpected_internal"
    assert "secret implementation detail" not in result.diagnostics[0].message
    assert state is not None
    assert state.refresh_state is RefreshState.ERROR


def test_waiter_cancellation_does_not_cancel_shared_refresh() -> None:
    asyncio.run(_waiter_cancellation_does_not_cancel_shared_refresh())


async def _waiter_cancellation_does_not_cancel_shared_refresh() -> None:
    entered = Event()
    release = Event()
    attempts = 0
    instrument = DEFAULT_INSTRUMENT_MASTER.resolve("000001.SZ")

    def fetcher(instrument: InstrumentId) -> DataEnvelope[NormalizedSnapshot]:
        nonlocal attempts
        attempts += 1
        entered.set()
        release.wait(timeout=2)
        return _success(instrument)

    coordinator = SnapshotCoordinator(fetcher)
    waiter_a = asyncio.create_task(coordinator.get([instrument]))
    waiter_b = asyncio.create_task(coordinator.get([instrument]))
    assert await asyncio.to_thread(entered.wait, 1)
    waiter_a.cancel()
    try:
        await waiter_a
    except asyncio.CancelledError:
        pass
    else:
        raise AssertionError("cancelled waiter must preserve cancellation")
    release.set()
    result_b = await waiter_b
    state = await coordinator.cache_state(instrument.symbol)

    assert attempts == 1
    assert result_b.items
    assert state is not None
    assert state.refresh_state is RefreshState.IDLE
    assert state.latest_diagnostic is None
