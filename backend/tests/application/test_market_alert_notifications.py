from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from finance_god.application.market_alert_notifications import (
    MarketAlertNotificationProjector,
)
from finance_god.infrastructure.persistence.market_monitor_models import (
    MarketAlertDispatchRow,
    MarketAlertRow,
)
from finance_god.infrastructure.persistence.models import Base
from finance_god.infrastructure.persistence.workspace_models import (
    NotificationRow,
    UserEventRow,
    UserMarketFocusRow,
)


def test_projects_once_for_interested_owner_and_keeps_unrelated_owner_isolated(
    tmp_path,
) -> None:
    asyncio.run(_exercise_projection(tmp_path))


async def _exercise_projection(tmp_path) -> None:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'alert-projection.db'}"
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    now = datetime(2026, 7, 25, 3, 0, tzinfo=UTC)
    async with sessions() as session, session.begin():
        session.add_all(
            [
                UserMarketFocusRow(
                    owner_user_id="interested",
                    symbol="300750.SZ",
                    updated_at=now,
                ),
                UserMarketFocusRow(
                    owner_user_id="unrelated",
                    symbol="000001.SZ",
                    updated_at=now,
                ),
                MarketAlertRow(
                    alert_id="alert-1",
                    symbol="300750.SZ",
                    name="宁德时代",
                    kind="surge",
                    severity="error",
                    change_percent=Decimal("0.08"),
                    last=Decimal("205.50"),
                    message="价格窗口涨幅达到阈值",
                    provider_time="2026-07-25T03:00:00Z",
                    detected_at=now,
                ),
                MarketAlertDispatchRow(
                    alert_id="alert-1",
                    created_at=now,
                    attempt=0,
                ),
            ]
        )
    projector = MarketAlertNotificationProjector(sessions)
    assert await projector.dispatch_pending() == 1
    assert await projector.dispatch_pending() == 0
    async with sessions() as session:
        notifications = list(await session.scalars(select(NotificationRow)))
        events = list(await session.scalars(select(UserEventRow)))
        dispatch = await session.get(MarketAlertDispatchRow, "alert-1")
    assert [row.owner_user_id for row in notifications] == ["interested"]
    assert notifications[0].required is True
    assert notifications[0].details_json["symbol"] == "300750.SZ"
    assert [row.owner_user_id for row in events] == ["interested"]
    assert dispatch is not None and dispatch.dispatched_at is not None
    await engine.dispose()
