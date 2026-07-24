from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from types import TracebackType
from typing import Self

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from finance_god.market_data.monitor import (
    AlertKind,
    AlertSeverity,
    MarketAlert,
    MarketSnapshot,
)

from .market_monitor_models import MarketAlertRow, MarketSnapshotRow


class MarketMonitorRepository:
    """Read/write the latest snapshots and the global market-alert log."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_snapshot(self, symbol: str) -> MarketSnapshot | None:
        row = await self._session.get(MarketSnapshotRow, symbol)
        return _snapshot(row) if row is not None else None

    async def upsert_snapshot(self, snapshot: MarketSnapshot) -> None:
        now = datetime.now(UTC)
        await self._session.merge(
            MarketSnapshotRow(
                symbol=snapshot.symbol,
                name=snapshot.name,
                last=snapshot.last,
                change_percent=snapshot.change_percent,
                provider_time=snapshot.provider_time,
                frequency=snapshot.frequency,
                freshness=snapshot.freshness,
                retrieved_at=snapshot.retrieved_at,
                updated_at=now,
            )
        )
        await self._session.flush()

    async def list_snapshots(self) -> list[MarketSnapshot]:
        rows = await self._session.scalars(
            select(MarketSnapshotRow).order_by(MarketSnapshotRow.symbol)
        )
        return [_snapshot(row) for row in rows]

    async def insert_alert(self, alert: MarketAlert) -> None:
        try:
            self._session.add(
                MarketAlertRow(
                    alert_id=alert.alert_id,
                    symbol=alert.symbol,
                    name=alert.name,
                    kind=alert.kind.value,
                    severity=alert.severity.value,
                    change_percent=alert.change_percent,
                    last=alert.last,
                    message=alert.message,
                    provider_time=alert.provider_time,
                    detected_at=alert.detected_at,
                )
            )
            await self._session.flush()
        except IntegrityError:
            # Idempotent: the same alert_id was already recorded.
            pass

    async def list_alerts(self, *, limit: int = 50) -> list[MarketAlert]:
        rows = await self._session.scalars(
            select(MarketAlertRow)
            .order_by(MarketAlertRow.detected_at.desc(), MarketAlertRow.id.desc())
            .limit(limit)
        )
        return [_alert(row) for row in rows]


def _snapshot(row: MarketSnapshotRow) -> MarketSnapshot:
    return MarketSnapshot(
        symbol=row.symbol,
        name=row.name,
        last=row.last,
        change_percent=row.change_percent,
        provider_time=row.provider_time,
        frequency=row.frequency,
        freshness=row.freshness,
        retrieved_at=row.retrieved_at,
    )


def _alert(row: MarketAlertRow) -> MarketAlert:
    return MarketAlert(
        alert_id=row.alert_id,
        symbol=row.symbol,
        name=row.name,
        kind=AlertKind(row.kind),
        severity=AlertSeverity(row.severity),
        change_percent=row.change_percent,
        last=row.last,
        message=row.message,
        provider_time=row.provider_time,
        detected_at=row.detected_at,
    )


class MarketMonitorUnitOfWork:
    """One transaction and repository for a market-monitor operation."""

    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> Self:
        if self._session is not None:
            raise RuntimeError("market monitor unit of work is already active")
        self._session = self._session_factory()
        self._transaction = await self._session.begin()
        self.monitor = MarketMonitorRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        if self._transaction.is_active:
            await self._transaction.rollback()
        assert self._session is not None
        await self._session.close()
        self._session = None

    async def commit(self) -> None:
        await self._transaction.commit()
