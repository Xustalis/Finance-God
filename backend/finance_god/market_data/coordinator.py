"""Per-instrument singleflight and visible stale-while-refresh state."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from time import monotonic
from typing import Generic, Protocol, TypeVar
from zoneinfo import ZoneInfo

from .contracts import (
    DataDiagnostic,
    DataEnvelope,
    DiagnosticCode,
    EmptyMeaning,
    FreshnessStatus,
    InstrumentId,
    NormalizedSnapshot,
)
from .errors import MarketDataError
from .normalization import diagnostic

_UTC = ZoneInfo("UTC")
T = TypeVar("T")


class RefreshState(StrEnum):
    IDLE = "idle"
    REFRESHING = "refreshing"
    ERROR = "error"


@dataclass(frozen=True)
class CacheEntry(Generic[T]):
    last_success: tuple[T, ...]
    last_success_at: float | None
    last_attempt: datetime | None
    last_attempt_at: float | None
    refresh_state: RefreshState
    latest_diagnostic: DataDiagnostic | None


@dataclass(frozen=True)
class CoordinatedResult(Generic[T]):
    items: tuple[T, ...]
    diagnostics: tuple[DataDiagnostic, ...]
    states: tuple[tuple[str, CacheEntry[T]], ...]


class SnapshotFetcher(Protocol):
    def __call__(
        self, instrument: InstrumentId
    ) -> DataEnvelope[NormalizedSnapshot]: ...


class SnapshotCoordinator:
    """One cache and one task per canonical symbol; network awaits outside locks."""

    def __init__(
        self,
        fetcher: SnapshotFetcher,
        *,
        refresh_after_seconds: float = 0.9,
        error_retry_after_seconds: float = 5.0,
        max_transient_retries: int = 0,
        clock: Callable[[], float] = monotonic,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if refresh_after_seconds <= 0:
            raise ValueError("refresh_after_seconds must be positive")
        if error_retry_after_seconds <= 0:
            raise ValueError("error_retry_after_seconds must be positive")
        if max_transient_retries != 0:
            raise ValueError(
                "coordinator retries are disabled; PandaData transport owns attempts"
            )
        self._fetcher = fetcher
        self._refresh_after_seconds = refresh_after_seconds
        self._error_retry_after_seconds = error_retry_after_seconds
        self._clock = clock
        self._now = now or (lambda: datetime.now(_UTC))
        self._cache: dict[str, CacheEntry[NormalizedSnapshot]] = {}
        self._tasks: dict[str, asyncio.Task[DataEnvelope[NormalizedSnapshot]]] = {}
        self._lock = asyncio.Lock()

    async def get(
        self, instruments: Iterable[InstrumentId]
    ) -> CoordinatedResult[NormalizedSnapshot]:
        requested = _unique_instruments(instruments)
        initial_tasks: list[asyncio.Future[DataEnvelope[NormalizedSnapshot]]] = []
        immediate_items: list[NormalizedSnapshot] = []
        immediate_diagnostics: list[DataDiagnostic] = []
        async with self._lock:
            current = self._clock()
            for instrument in requested:
                key = instrument.symbol
                entry = self._cache.get(key)
                if entry is None:
                    task = self._tasks.get(key)
                    if task is None:
                        task = self._start_refresh(instrument)
                    initial_tasks.append(asyncio.shield(task))
                    continue
                if entry.refresh_state is RefreshState.REFRESHING:
                    task = self._tasks.get(key)
                    if task is not None and not entry.last_success:
                        initial_tasks.append(asyncio.shield(task))
                        continue
                if self._is_fresh(entry, current):
                    immediate_items.extend(entry.last_success)
                    if entry.latest_diagnostic is not None:
                        immediate_diagnostics.append(entry.latest_diagnostic)
                    continue
                if self._should_refresh(key, entry, current):
                    self._start_refresh(instrument)
                immediate_items.extend(
                    _mark_stale(item, entry.latest_diagnostic)
                    for item in entry.last_success
                )
                if entry.latest_diagnostic is not None:
                    immediate_diagnostics.append(entry.latest_diagnostic)

        if initial_tasks:
            envelopes = await asyncio.gather(*initial_tasks)
            for envelope in envelopes:
                immediate_items.extend(envelope.items)
                immediate_diagnostics.extend(envelope.diagnostics)

        async with self._lock:
            states = tuple(
                (instrument.symbol, self._cache[instrument.symbol])
                for instrument in requested
                if instrument.symbol in self._cache
            )
        by_symbol = {item.instrument.symbol: item for item in immediate_items}
        return CoordinatedResult(
            items=tuple(
                by_symbol[instrument.symbol]
                for instrument in requested
                if instrument.symbol in by_symbol
            ),
            diagnostics=tuple(
                {item.fingerprint: item for item in immediate_diagnostics}.values()
            ),
            states=states,
        )

    async def wait_for_refreshes(self) -> None:
        async with self._lock:
            tasks = tuple(self._tasks.values())
        if tasks:
            await asyncio.gather(*(asyncio.shield(task) for task in tasks))

    async def cache_state(self, symbol: str) -> CacheEntry[NormalizedSnapshot] | None:
        async with self._lock:
            return self._cache.get(symbol.strip().upper())

    def _start_refresh(
        self, instrument: InstrumentId
    ) -> asyncio.Task[DataEnvelope[NormalizedSnapshot]]:
        key = instrument.symbol
        existing = self._tasks.get(key)
        if existing is not None:
            return existing
        previous = self._cache.get(key)
        self._cache[key] = CacheEntry(
            last_success=previous.last_success if previous else (),
            last_success_at=previous.last_success_at if previous else None,
            last_attempt=self._aware_now(),
            last_attempt_at=self._clock(),
            refresh_state=RefreshState.REFRESHING,
            latest_diagnostic=previous.latest_diagnostic if previous else None,
        )
        task = asyncio.create_task(self._refresh(instrument))
        self._tasks[key] = task
        return task

    async def _refresh(
        self, instrument: InstrumentId
    ) -> DataEnvelope[NormalizedSnapshot]:
        key = instrument.symbol
        try:
            envelope = await self._fetch_once(instrument)
            async with self._lock:
                prior = self._cache[key]
                if envelope.items:
                    self._cache[key] = CacheEntry(
                        last_success=envelope.items,
                        last_success_at=self._clock(),
                        last_attempt=prior.last_attempt,
                        last_attempt_at=prior.last_attempt_at,
                        refresh_state=RefreshState.IDLE,
                        latest_diagnostic=(
                            envelope.diagnostics[-1] if envelope.diagnostics else None
                        ),
                    )
                else:
                    issue = (
                        envelope.diagnostics[-1]
                        if envelope.diagnostics
                        else diagnostic(
                            code=DiagnosticCode.UNEXPECTED_MISSING,
                            scope=key,
                            message="refresh returned no item and no diagnostic",
                            endpoint=None,
                            empty_meaning=EmptyMeaning.UNEXPECTED_MISSING,
                        )
                    )
                    self._cache[key] = replace(
                        prior,
                        refresh_state=RefreshState.ERROR,
                        latest_diagnostic=issue,
                    )
                    if prior.last_success:
                        return DataEnvelope(
                            tuple(
                                _mark_stale(item, issue) for item in prior.last_success
                            ),
                            (issue,),
                            EmptyMeaning.NOT_EMPTY,
                        )
            return envelope
        except asyncio.CancelledError:
            issue = diagnostic(
                code=DiagnosticCode.REFRESH_FAILED,
                scope=key,
                message="market-data refresh was cancelled",
                endpoint=None,
                empty_meaning=EmptyMeaning.UNEXPECTED_MISSING,
            )
            await self._record_failure(key, issue)
            raise
        except BaseException as error:  # noqa: BLE001 - state must not remain refreshing
            issue = _failure_diagnostic(key, error)
            fallback = await self._record_failure(key, issue)
            if fallback is not None:
                return fallback
            return DataEnvelope((), (issue,), EmptyMeaning.UNEXPECTED_MISSING)
        finally:
            async with self._lock:
                self._tasks.pop(key, None)

    async def _record_failure(
        self,
        key: str,
        issue: DataDiagnostic,
    ) -> DataEnvelope[NormalizedSnapshot] | None:
        async with self._lock:
            prior = self._cache[key]
            self._cache[key] = replace(
                prior,
                refresh_state=RefreshState.ERROR,
                latest_diagnostic=issue,
            )
            if prior.last_success:
                return DataEnvelope(
                    tuple(_mark_stale(item, issue) for item in prior.last_success),
                    (issue,),
                    EmptyMeaning.NOT_EMPTY,
                )
        return None

    async def _fetch_once(
        self, instrument: InstrumentId
    ) -> DataEnvelope[NormalizedSnapshot]:
        return await asyncio.to_thread(self._fetcher, instrument)

    def _is_fresh(self, entry: CacheEntry[NormalizedSnapshot], current: float) -> bool:
        return (
            entry.last_success_at is not None
            and entry.refresh_state is RefreshState.IDLE
            and current - entry.last_success_at < self._refresh_after_seconds
        )

    def _should_refresh(
        self,
        key: str,
        entry: CacheEntry[NormalizedSnapshot],
        current: float,
    ) -> bool:
        if key in self._tasks:
            return False
        return not (
            entry.refresh_state is RefreshState.ERROR
            and entry.last_attempt_at is not None
            and current - entry.last_attempt_at < self._error_retry_after_seconds
        )

    def _aware_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            raise ValueError("coordinator clock must return timezone-aware datetime")
        return value.astimezone(_UTC)


def _failure_diagnostic(key: str, error: BaseException) -> DataDiagnostic:
    if isinstance(error, MarketDataError):
        return diagnostic(
            code=(
                DiagnosticCode.TRANSIENT_UPSTREAM
                if error.retryable
                else DiagnosticCode.REFRESH_FAILED
            ),
            scope=key,
            message=error.public_message,
            endpoint=error.endpoint,
            retryable=error.retryable,
            empty_meaning=EmptyMeaning.UNEXPECTED_MISSING,
            details={"trace_id": error.trace_id},
        )
    return diagnostic(
        code=DiagnosticCode.UNEXPECTED_INTERNAL,
        scope=key,
        message="market-data refresh failed internally",
        endpoint=None,
        empty_meaning=EmptyMeaning.UNEXPECTED_MISSING,
        details={"exception_type": type(error).__name__},
    )


def _unique_instruments(
    instruments: Iterable[InstrumentId],
) -> tuple[InstrumentId, ...]:
    unique = {item.symbol: item for item in instruments}
    if not unique:
        raise ValueError("at least one instrument is required")
    if len(unique) > 40:
        raise ValueError("at most 40 instruments are allowed")
    return tuple(unique.values())


def _mark_stale(
    item: NormalizedSnapshot, issue: DataDiagnostic | None
) -> NormalizedSnapshot:
    reason = (
        f"cached value retained after refresh failure: {issue.code.value}"
        if issue is not None
        else "cached value is awaiting upstream refresh"
    )
    freshness = item.freshness.model_copy(
        update={
            "status": FreshnessStatus.STALE,
            "reason": reason,
        }
    )
    return item.model_copy(update={"freshness": freshness})
