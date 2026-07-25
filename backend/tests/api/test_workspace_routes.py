from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from finance_god.api.workspace_routes import create_workspace_routes
from finance_god.infrastructure.persistence.models import Base


async def _resolve_server_user(_request) -> str:
    return "server-user"


def test_workspace_routes_use_server_resolved_owner(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'workspace-api.db'}"
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    asyncio.run(_create_schema(engine))
    app = Starlette(
        routes=[
            Mount(
                "/api/v1",
                routes=create_workspace_routes(
                    session_factory=session_factory,
                    owner_resolver=_resolve_server_user,
                ),
            )
        ]
    )
    try:
        with TestClient(app) as client:
            created = client.post(
                "/api/v1/watchlists",
                json={"name": "China equities", "description": "liquid names"},
                headers={"x-finance-god-owner-id": "untrusted-user"},
            )
            assert created.status_code == 201
            assert created.json()["owner_user_id"] == "server-user"

            listed = client.get("/api/v1/watchlists")
            assert listed.status_code == 200
            assert len(listed.json()) == 1

            group_id = created.json()["group_id"]
            updated = client.patch(
                f"/api/v1/watchlists/{group_id}",
                json={
                    "name": "China equities core",
                    "description": "liquid names",
                    "expected_revision": 1,
                },
            )
            assert updated.status_code == 200
            assert updated.json()["revision"] == 2

            stale = client.patch(
                f"/api/v1/watchlists/{group_id}",
                json={
                    "name": "stale write",
                    "description": None,
                    "expected_revision": 1,
                },
            )
            assert stale.status_code == 409
            assert stale.json()["error"]["code"] == "REVISION_CONFLICT"
    finally:
        asyncio.run(engine.dispose())

async def _create_schema(engine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

def test_notification_history_includes_read_and_honors_filters(tmp_path) -> None:
    """Toast hide ≠ read; history returns persisted unread|read only."""
    from datetime import UTC, datetime

    from finance_god.domain.models import (
        AuditReference,
        Notification,
        NotificationCategory,
        NotificationSeverity,
        NotificationStatus,
    )

    database_url = f"sqlite+aiosqlite:///{tmp_path / 'notification-history.db'}"
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    asyncio.run(_create_schema(engine))
    app = Starlette(
        routes=[
            Mount(
                "/api",
                routes=create_workspace_routes(
                    session_factory=session_factory,
                    owner_resolver=_resolve_server_user,
                ),
            )
        ]
    )
    now = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)

    async def seed() -> None:
        from finance_god.infrastructure.persistence.workspace_uow import WorkspaceUnitOfWork

        async with WorkspaceUnitOfWork(session_factory) as uow:
            await uow.notifications.create_notification(
                Notification(
                    notification_id="n-unread",
                    owner_user_id="server-user",
                    category=NotificationCategory.MARKET,
                    severity=NotificationSeverity.INFO,
                    title="Unread alert",
                    message="still open",
                    source_object_type="MarketAlert",
                    source_object_id="alert-1",
                    source_version="1",
                    required=False,
                    status=NotificationStatus.UNREAD,
                    created_at=now,
                    audit_reference=AuditReference(
                        audit_id="audit-unread",
                        actor_id="system",
                        recorded_at=now,
                    ),
                )
            )
            await uow.notifications.create_notification(
                Notification(
                    notification_id="n-read",
                    owner_user_id="server-user",
                    category=NotificationCategory.WORKFLOW,
                    severity=NotificationSeverity.WARNING,
                    title="Read alert",
                    message="already seen",
                    source_object_type="WorkflowRun",
                    source_object_id="run-1",
                    source_version="1",
                    required=False,
                    status=NotificationStatus.READ,
                    created_at=now,
                    read_at=now,
                    audit_reference=AuditReference(
                        audit_id="audit-read",
                        actor_id="system",
                        recorded_at=now,
                    ),
                )
            )
            await uow.commit()

    asyncio.run(seed())
    try:
        with TestClient(app) as client:
            unread = client.get("/api/notifications")
            assert unread.status_code == 200
            unread_ids = {item["notification_id"] for item in unread.json()}
            assert unread_ids == {"n-unread"}

            history = client.get("/api/notifications/history", params={"limit": 50, "include_read": "true"})
            assert history.status_code == 200
            history_ids = {item["notification_id"] for item in history.json()}
            assert history_ids == {"n-unread", "n-read"}

            unread_only = client.get(
                "/api/notifications/history",
                params={"limit": 50, "include_read": "false"},
            )
            assert unread_only.status_code == 200
            assert {item["notification_id"] for item in unread_only.json()} == {"n-unread"}

            bad_limit = client.get("/api/notifications/history", params={"limit": "nope"})
            assert bad_limit.status_code == 400
    finally:
        asyncio.run(engine.dispose())
