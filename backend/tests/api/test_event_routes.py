from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from finance_god.api.event_routes import _stream, create_event_routes
from finance_god.infrastructure.persistence.models import Base
from finance_god.infrastructure.persistence.workspace_models import (
    NotificationDeliveryRow,
    NotificationRow,
    UserEventRow,
)


async def _owner(_request) -> str:
    return "owner-1"


def test_event_route_rejects_invalid_cursor(tmp_path) -> None:
    engine, sessions, app = asyncio.run(_app(tmp_path))
    try:
        with TestClient(app) as client:
            response = client.get("/api/events", params={"cursor": "bad"})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVALID_EVENT_CURSOR"
    finally:
        asyncio.run(engine.dispose())


def test_event_stream_is_owner_scoped_and_resumable(tmp_path) -> None:
    asyncio.run(_exercise_stream(tmp_path))


async def _app(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'events.db'}"
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    app = Starlette(
        routes=[
            Mount(
                "/api",
                routes=create_event_routes(
                    session_factory=sessions,
                    owner_resolver=_owner,
                    heartbeat_seconds=60,
                    poll_seconds=0,
                ),
            )
        ]
    )
    return engine, sessions, app


async def _exercise_stream(tmp_path) -> None:
    engine, sessions, _app_instance = await _app(tmp_path)
    now = datetime(2026, 7, 25, 3, 0, tzinfo=UTC)
    async with sessions() as session, session.begin():
        for owner, suffix in (("owner-1", "mine"), ("owner-2", "other")):
            notification_id = f"notification-{suffix}"
            session.add(
                NotificationRow(
                    notification_id=notification_id,
                    owner_user_id=owner,
                    category="market",
                    severity="warning",
                    title=suffix,
                    message=suffix,
                    details_json={"symbol": "300750.SZ"},
                    source_object_type="MarketAlert",
                    source_object_id=f"alert-{suffix}",
                    source_version="v1",
                    required=False,
                    status="unread",
                    created_at=now,
                    audit_id=f"audit-{suffix}",
                    audit_actor_id="system",
                    audit_recorded_at=now,
                )
            )
            await session.flush()
            session.add(
                UserEventRow(
                    event_id=f"event-{suffix}",
                    owner_user_id=owner,
                    event_type="notification.created",
                    notification_id=notification_id,
                    fact_version="v1",
                    payload_json={"notification_id": notification_id},
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

    class Request:
        calls = 0

        async def is_disconnected(self) -> bool:
            self.calls += 1
            return self.calls > 1

    chunks = []
    async for chunk in _stream(Request(), sessions, "owner-1", 0, 60, 0):
        chunks.append(chunk.decode())
    payload = "".join(chunks)
    assert "notification-mine" in payload
    assert "notification-other" not in payload
    data_line = next(
        line for line in payload.splitlines() if line.startswith("data: ")
    )
    assert json.loads(data_line.removeprefix("data: "))["event_type"] == (
        "notification.created"
    )
    await engine.dispose()
