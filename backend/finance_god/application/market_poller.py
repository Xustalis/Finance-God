"""Server-side market poller: the always-on ingestion workflow.

At a configured (deliberately long) interval it pulls a bounded instrument
universe through the normalized market-data application, persists the latest
snapshot per instrument, and records a global alert when a move crosses the
configured threshold. It never fabricates values: instruments the upstream
cannot price are simply skipped this cycle.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from finance_god.infrastructure.persistence.market_monitor_repository import (
    MarketMonitorUnitOfWork,
)
from finance_god.market_data.monitor import (
    MarketAlert,
    MarketSnapshot,
    detect_market_alert,
)

_LOGGER = logging.getLogger(__name__)

QuotesProvider = Callable[[list[str]], Awaitable[object]]
Clock = Callable[[], datetime]
IdGenerator = Callable[[], str]
SnapshotObserver = Callable[[MarketSnapshot], Awaitable[None]]
AlertDispatcher = Callable[[], Awaitable[int]]


class MarketPoller:
    """Poll a bounded universe, persist snapshots, and record crossing alerts."""

    def __init__(
        self,
        *,
        quotes_provider: QuotesProvider,
        uow_factory: Callable[[], MarketMonitorUnitOfWork],
        threshold: Decimal,
        escalate_threshold: Decimal | None = None,
        snapshot_observer: SnapshotObserver | None = None,
        alert_dispatcher: AlertDispatcher | None = None,
        clock: Clock | None = None,
        ids: IdGenerator | None = None,
    ) -> None:
        self._quotes = quotes_provider
        self._uow_factory = uow_factory
        self._threshold = threshold
        self._escalate_threshold = escalate_threshold
        self._snapshot_observer = snapshot_observer
        self._alert_dispatcher = alert_dispatcher
        self._clock = clock or (lambda: datetime.now(UTC))
        self._ids = ids or (lambda: f"market-alert-{uuid4().hex}")

    async def poll_once(self, symbols: list[str]) -> list[MarketAlert]:
        """Fetch, persist, and detect once; return the alerts newly recorded."""
        batch = await self._quotes(symbols)
        quotes = list(getattr(batch, "quotes", ()) or ())
        now = self._clock()
        created: list[MarketAlert] = []
        persisted: list[MarketSnapshot] = []
        if not quotes:
            return created
        async with self._uow_factory() as uow:
            for quote in quotes:
                current = _snapshot_from_quote(quote, now)
                if current is None:
                    continue
                previous = await uow.monitor.get_snapshot(current.symbol)
                alert = detect_market_alert(
                    previous=previous,
                    current=current,
                    threshold=self._threshold,
                    now=now,
                    alert_id=self._ids(),
                    escalate_threshold=self._escalate_threshold,
                )
                await uow.monitor.upsert_snapshot(current)
                persisted.append(current)
                if alert is not None:
                    await uow.monitor.insert_alert(alert)
                    created.append(alert)
            await uow.commit()
        if self._snapshot_observer is not None:
            for snapshot in persisted:
                try:
                    await self._snapshot_observer(snapshot)
                except Exception as error:  # noqa: BLE001 - one strategy must not stop market ingestion
                    _LOGGER.exception(
                        "market snapshot observer failed for %s: %s",
                        snapshot.symbol,
                        type(error).__name__,
                    )
        if self._alert_dispatcher is not None:
            try:
                await self._alert_dispatcher()
            except Exception as error:  # noqa: BLE001 - durable outbox retries next cycle
                _LOGGER.exception(
                    "market alert projection failed; outbox remains pending: %s",
                    type(error).__name__,
                )
        if created:
            _LOGGER.info("market poller recorded %d alert(s)", len(created))
        return created

    async def run_forever(
        self,
        *,
        symbols: list[str],
        interval_seconds: float,
        stop_event: asyncio.Event,
    ) -> None:
        """Poll on an interval until ``stop_event`` is set; degrade on failure."""
        while not stop_event.is_set():
            try:
                await self.poll_once(symbols)
            except Exception as error:  # noqa: BLE001 - a poll failure must not kill the loop
                _LOGGER.warning(
                    "market poll cycle failed: %s", type(error).__name__
                )
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
            except TimeoutError:
                continue


def _snapshot_from_quote(quote: object, now: datetime) -> MarketSnapshot | None:
    """Build a snapshot from a normalized quote; skip anything unpriceable."""
    try:
        last = getattr(quote, "last")
        symbol = getattr(quote, "symbol")
    except AttributeError:
        return None
    if last is None or not symbol:
        return None
    return MarketSnapshot(
        symbol=str(symbol),
        name=str(getattr(quote, "name", None) or symbol),
        last=Decimal(str(last)),
        change_percent=(
            Decimal(str(getattr(quote, "change_percent")))
            if getattr(quote, "change_percent", None) is not None
            else None
        ),
        provider_time=str(getattr(quote, "provider_time", None) or "unknown"),
        frequency=str(getattr(quote, "frequency", None) or "unknown"),
        freshness=str(getattr(quote, "freshness", None) or "unknown"),
        retrieved_at=getattr(quote, "retrieved_at", None) or now,
    )
