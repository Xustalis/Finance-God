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
