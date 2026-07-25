"""Project global market alerts into durable, owner-scoped notifications."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from finance_god.infrastructure.persistence.market_monitor_models import (
    MarketAlertDispatchRow,
    MarketAlertRow,
)
from finance_god.infrastructure.persistence.models import (
    AccountRow,
    PositionProjectionRow,
)
from finance_god.infrastructure.persistence.workspace_models import (
    NotificationDeliveryRow,
    NotificationPreferenceRow,
    NotificationRow,
    UserEventRow,
    UserMarketFocusRow,
    WatchlistGroupRow,
    WatchlistInstrumentRow,
)

_LOGGER = logging.getLogger(__name__)


class MarketAlertNotificationProjector:
    """Idempotently map pending alert outbox rows to interested owners."""

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    async def dispatch_pending(self, *, limit: int = 100) -> int:
        async with self._session_factory() as session:
            pending = list(
                await session.scalars(
                    select(MarketAlertDispatchRow)
                    .where(MarketAlertDispatchRow.dispatched_at.is_(None))
                    .order_by(MarketAlertDispatchRow.created_at)
                    .limit(limit)
                )
            )
        dispatched = 0
        for item in pending:
            try:
                await self._dispatch_one(item.alert_id)
                dispatched += 1
            except Exception as error:
                await self._record_failure(item.alert_id, error)
        return dispatched

    async def _dispatch_one(self, alert_id: str) -> None:
        async with self._session_factory() as session, session.begin():
            dispatch = await session.get(MarketAlertDispatchRow, alert_id)
            if dispatch is None or dispatch.dispatched_at is not None:
                return
            alert = await session.scalar(
                select(MarketAlertRow).where(MarketAlertRow.alert_id == alert_id)
            )
            if alert is None:
                raise RuntimeError("market alert outbox references missing alert")
            owners = await _interested_owners(session, alert.symbol)
            now = datetime.now(UTC)
            created = 0
            for owner_id in owners:
                if not await _market_notifications_enabled(session, owner_id):
                    continue
                if await _create_owner_event(session, owner_id, alert, now):
                    created += 1
            dispatch.dispatched_at = now
            dispatch.attempt += 1
            dispatch.error = None
            _LOGGER.info(
                "market alert projected alert_id=%s symbol=%s matched=%d created=%d "
                "delay_seconds=%.3f",
                alert.alert_id,
                alert.symbol,
                len(owners),
                created,
                max(0.0, (now - alert.detected_at).total_seconds()),
            )

    async def _record_failure(self, alert_id: str, error: Exception) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                update(MarketAlertDispatchRow)
                .where(MarketAlertDispatchRow.alert_id == alert_id)
                .values(
                    attempt=MarketAlertDispatchRow.attempt + 1,
                    error=f"{type(error).__name__}: {error}"[:500],
                )
            )


async def _interested_owners(session: AsyncSession, symbol: str) -> set[str]:
    focus = await session.scalars(
        select(UserMarketFocusRow.owner_user_id).where(
            UserMarketFocusRow.symbol == symbol
        )
    )
    watchlists = await session.scalars(
        select(WatchlistGroupRow.owner_user_id)
        .join(
            WatchlistInstrumentRow,
            WatchlistInstrumentRow.group_id == WatchlistGroupRow.group_id,
        )
        .where(WatchlistInstrumentRow.instrument_id == symbol)
    )
    positions = await session.scalars(
        select(AccountRow.owner_user_id)
        .join(
            PositionProjectionRow,
            PositionProjectionRow.account_id == AccountRow.account_id,
        )
        .where(
            AccountRow.current.is_(True),
            PositionProjectionRow.instrument_id == symbol,
            or_(
                PositionProjectionRow.long_quantity > Decimal("0"),
                PositionProjectionRow.short_quantity > Decimal("0"),
            ),
        )
    )
    return set(focus) | set(watchlists) | set(positions)


async def _market_notifications_enabled(
    session: AsyncSession, owner_id: str
) -> bool:
    preference = await session.get(NotificationPreferenceRow, owner_id)
    if preference is None:
        return True
    return preference.preferences_json.get("market", True) is not False


async def _create_owner_event(
    session: AsyncSession,
    owner_id: str,
    alert: MarketAlertRow,
    now: datetime,
) -> bool:
    notification_id = str(
        uuid5(NAMESPACE_URL, f"finance-god:market-alert:{owner_id}:{alert.alert_id}")
    )
    existing = await session.get(NotificationRow, notification_id)
    if existing is not None:
        return False
    required = alert.severity == "error"
    severity = "required" if required else "warning"
    details = {
        "symbol": alert.symbol,
        "provider_time": alert.provider_time,
        "detected_at": alert.detected_at.isoformat(),
        "alert_kind": alert.kind,
        "change_percent": str(alert.change_percent),
        "last": str(alert.last),
    }
    session.add(
        NotificationRow(
            notification_id=notification_id,
            owner_user_id=owner_id,
            category="market",
            severity=severity,
            title=f"{alert.name}重大行情提醒",
            message=alert.message,
            details_json=details,
            source_object_type="MarketAlert",
            source_object_id=alert.alert_id,
            source_version=alert.provider_time,
            required=required,
            status="unread",
            created_at=now,
            audit_id=f"audit:{notification_id}",
            audit_actor_id="market-alert-projector",
            audit_recorded_at=now,
        )
    )
    await session.flush()
    event_id = str(uuid5(NAMESPACE_URL, f"finance-god:event:{notification_id}"))
    payload = {
        "notification_id": notification_id,
        "severity": severity,
        "required": required,
        "title": f"{alert.name}重大行情提醒",
        "message": alert.message,
        "status": "unread",
        "created_at": now.isoformat(),
        "details": details,
    }
    session.add(
        UserEventRow(
            event_id=event_id,
            owner_user_id=owner_id,
            event_type="notification.created",
            notification_id=notification_id,
            fact_version=alert.provider_time,
            payload_json=payload,
            occurred_at=now,
        )
    )
    session.add(
        NotificationDeliveryRow(
            notification_id=notification_id,
            channel="in_app",
            attempt=0,
            status="available",
        )
    )
    return True
