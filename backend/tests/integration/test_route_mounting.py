"""P2 集成测试：统一入口 app.main:app 的路由挂载完整性。

覆盖三个路由族的可达性：
- /api/v1/*（FastAPI include_router）
- /api/finance/*（先挂载的 finance_app）
- /api/*（后挂载的 finance_app 兼容路径族）
"""

import asyncio

import pytest
import server as finance_server
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finance_god.infrastructure.persistence.models import Base as FinanceBase


def test_v1_auth_me_is_mounted_and_requires_auth(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me")

    # 路由存在但未携带凭据：401 而非路由缺失的 404
    assert response.status_code == 401


def test_live_is_reachable_via_api_and_api_finance(client: TestClient) -> None:
    plain = client.get("/api/live")
    finance = client.get("/api/finance/live")

    assert plain.status_code == 200
    assert plain.json() == {"liveness": "live"}
    assert finance.status_code == 200
    assert finance.json() == {"liveness": "live"}


def test_simulation_current_account_requires_bearer_token(
    client: TestClient,
) -> None:
    response = client.get("/api/simulation/accounts/current")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_workspace_requires_valid_bearer_token(client: TestClient) -> None:
    missing = client.get("/api/workspace/watchlists")
    invalid = client.get(
        "/api/workspace/watchlists",
        headers={"Authorization": "Bearer invalid"},
    )

    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "UNAUTHORIZED"
    assert invalid.status_code == 401
    assert invalid.json()["error"]["code"] == "UNAUTHORIZED"


def test_workspace_uses_jwt_subject_and_isolates_users(
    client: TestClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_create_finance_schema(session_factory))
    monkeypatch.setattr(finance_server, "create_db_session", session_factory)
    first = client.post(
        "/api/v1/auth/register",
        json={"email": "workspace-a@example.com", "password": "correct-horse-123"},
    ).json()["data"]
    second = client.post(
        "/api/v1/auth/register",
        json={"email": "workspace-b@example.com", "password": "correct-horse-123"},
    ).json()["data"]

    created = client.post(
        "/api/workspace/watchlists",
        json={"name": "A only"},
        headers={
            "Authorization": f"Bearer {first['access_token']}",
            "x-finance-god-owner-id": second["user"]["id"],
        },
    )
    assert created.status_code == 201
    assert created.json()["owner_user_id"] == first["user"]["id"]

    first_list = client.get(
        "/api/workspace/watchlists",
        headers={"Authorization": f"Bearer {first['access_token']}"},
    )
    second_list = client.get(
        "/api/workspace/watchlists",
        headers={"Authorization": f"Bearer {second['access_token']}"},
    )
    assert len(first_list.json()) == 1
    assert second_list.json() == []


async def _create_finance_schema(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.kw["bind"].begin() as connection:
        await connection.run_sync(FinanceBase.metadata.create_all)


class _StubQuotesResult:
    quotes = [{"symbol": "600519.SH"}]

    def model_dump(self, mode: str = "json") -> dict:
        return {"provider": "PandaData", "quotes": self.quotes}


class _StubMarketApplication:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def quotes(self, symbols: list[str]) -> _StubQuotesResult:
        self.calls.append(list(symbols))
        return _StubQuotesResult()


def test_market_quotes_route_is_reachable_without_real_provider(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 用桩替换 server 模块级市场数据服务，禁止真实调用 PandaData。
    stub = _StubMarketApplication()
    monkeypatch.setattr(finance_server, "market_data", object())
    monkeypatch.setattr(finance_server, "market_application", stub)

    response = client.get("/api/market/quotes", params={"symbols": "600519.SH"})

    assert response.status_code != 404
    assert response.status_code == 200
    assert response.json()["quotes"] == [{"symbol": "600519.SH"}]
    assert stub.calls == [["600519.SH"]]
