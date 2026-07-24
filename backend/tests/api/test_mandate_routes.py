from __future__ import annotations

import asyncio
import itertools
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from finance_god.api.mandate_routes import create_mandate_routes
from finance_god.infrastructure.persistence.models import Base

NOW = datetime(2026, 7, 24, 8, tzinfo=UTC)

LIMITS = {
    "max_single_order_amount": "1000000",
    "max_daily_turnover_amount": "5000000",
    "max_single_asset_ratio": "1",
    "max_broad_etf_ratio": "1",
    "max_otc_fund_ratio": "1",
    "max_industry_ratio": "1",
    "max_gross_ratio": "1",
    "max_short_gross_ratio": "1",
    "max_single_short_ratio": "1",
    "max_price_deviation_ratio": "1",
    "max_all_in_cost_ratio": "1",
    "max_slippage_bps": "100",
}


class _Clock:
    def now(self) -> datetime:
        return NOW


class _IDs:
    def __init__(self) -> None:
        self._counter = itertools.count(1)

    def new_id(self, prefix: str) -> str:
        return f"{prefix}-{next(self._counter)}"


async def _resolve_owner(_request) -> str:
    return "server-user"


def _save_body(expected_revision: int, **overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "expected_revision": expected_revision,
        "autonomy_level": "L1",
        "allowed_markets": ["CN", "HK"],
        "allowed_assets": ["stock", "etf"],
        "allowed_sides": ["buy", "sell"],
        "allowed_order_types": ["limit", "market"],
        "short_markets": [],
        "limits": LIMITS,
        "valid_until": (NOW + timedelta(days=90)).isoformat(),
        "note": "tightened",
    }
    body.update(overrides)
    return body


def _client(tmp_path) -> TestClient:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'mandate-api.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    asyncio.run(_create_schema(engine))
    app = Starlette(
        routes=[
            Mount(
                "/mandate",
                routes=create_mandate_routes(
                    session_factory=session_factory,
                    owner_resolver=_resolve_owner,
                    clock=_Clock(),
                    ids=_IDs(),
                ),
            )
        ]
    )
    return TestClient(app)


async def _create_schema(engine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


def test_current_auto_creates_default_and_uses_server_owner(tmp_path) -> None:
    with _client(tmp_path) as client:
        response = client.get("/mandate/current", headers={"x-owner": "untrusted"})
        assert response.status_code == 200
        body = response.json()
        assert body["version"] == 1
        assert body["status"] == "active"
        assert body["autonomy_level"] == "L0"
        assert body["owner_user_id"] == "server-user"


def test_save_appends_version_and_rejects_stale_revision(tmp_path) -> None:
    with _client(tmp_path) as client:
        client.get("/mandate/current")
        saved = client.post("/mandate/versions", json=_save_body(1))
        assert saved.status_code == 201
        assert saved.json()["version"] == 2
        assert saved.json()["autonomy_level"] == "L1"

        stale = client.post("/mandate/versions", json=_save_body(1))
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "REVISION_CONFLICT"

        history = client.get("/mandate/history")
        assert [m["version"] for m in history.json()] == [2, 1]


def test_pause_resume_revoke_each_append_versions(tmp_path) -> None:
    with _client(tmp_path) as client:
        client.get("/mandate/current")
        paused = client.post("/mandate/pause", json={"expected_revision": 1})
        assert paused.status_code == 200
        assert paused.json()["status"] == "paused"
        assert paused.json()["version"] == 2

        resumed = client.post("/mandate/resume", json={"expected_revision": 2})
        assert resumed.json()["status"] == "active"

        revoked = client.post("/mandate/revoke", json={"expected_revision": 3})
        assert revoked.json()["status"] == "revoked"
        assert revoked.json()["version"] == 4


def test_impact_reports_zero_without_orders(tmp_path) -> None:
    with _client(tmp_path) as client:
        client.get("/mandate/current")
        impact = client.get("/mandate/impact")
        assert impact.status_code == 200
        assert impact.json() == {"evaluated": 0, "affected": []}
