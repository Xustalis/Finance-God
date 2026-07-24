"""HTTP boundary tests for the read-only market monitor endpoints."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
import server
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool
from starlette.requests import Request
from starlette.responses import JSONResponse

from finance_god.infrastructure.persistence.market_monitor_models import (  # noqa: F401
    MarketAlertRow,
)
from finance_god.infrastructure.persistence.market_monitor_repository import (
    MarketMonitorUnitOfWork,
)
from finance_god.infrastructure.persistence.models import Base
from finance_god.market_data.monitor import (
    AlertKind,
    AlertSeverity,
    MarketAlert,
    MarketSnapshot,
)

NOW = datetime(2026, 7, 24, 9, 30, tzinfo=UTC)


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _seed(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with MarketMonitorUnitOfWork(session_factory) as uow:
        await uow.monitor.upsert_snapshot(
            MarketSnapshot(
                symbol="600519.SH",
                name="贵州茅台",
                last=Decimal("1680.00"),
                change_percent=Decimal("0.061"),
                provider_time="2026-07-24T09:30:00+08:00",
                frequency="1min",
                freshness="realtime",
                retrieved_at=NOW,
            )
        )
        await uow.monitor.insert_alert(
            MarketAlert(
                alert_id="market-alert-1",
                symbol="600519.SH",
                name="贵州茅台",
                kind=AlertKind.SURGE,
                severity=AlertSeverity.WARNING,
                change_percent=Decimal("0.061"),
                last=Decimal("1680.00"),
                message="贵州茅台（600519.SH）大幅上涨 6.10%。",
                provider_time="2026-07-24T09:30:00+08:00",
                detected_at=NOW,
            )
        )
        await uow.commit()


@pytest.mark.asyncio
async def test_snapshots_endpoint_returns_cached_rows_with_upstream_time(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, "create_db_session", session_factory)
    await _seed(session_factory)

    response = await server.snapshots(_request(b""))
    payload = _payload(response)

    assert response.status_code == 200
    assert payload["provider"] == "PandaData"
    assert payload["snapshots"][0]["symbol"] == "600519.SH"
    assert payload["snapshots"][0]["provider_time"] == "2026-07-24T09:30:00+08:00"
    assert payload["snapshots"][0]["frequency"] == "1min"


@pytest.mark.asyncio
async def test_alerts_endpoint_returns_recorded_alerts(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, "create_db_session", session_factory)
    await _seed(session_factory)

    response = await server.alerts(_request(b"limit=10"))
    payload = _payload(response)

    assert response.status_code == 200
    assert len(payload["alerts"]) == 1
    assert payload["alerts"][0]["alert_id"] == "market-alert-1"
    assert payload["alerts"][0]["kind"] == "surge"
    assert payload["alerts"][0]["severity"] == "warning"


def _request(query_string: bytes) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/market/test",
            "query_string": query_string,
            "headers": [],
            "server": ("testserver", 80),
            "client": ("testclient", 123),
            "scheme": "http",
        }
    )


def _payload(response: JSONResponse) -> Any:
    return json.loads(bytes(response.body))
