"""P2 集成测试：统一入口 app.main:app 的路由挂载完整性。

覆盖三个路由族的可达性：
- /api/v1/*（FastAPI include_router）
- /api/finance/*（先挂载的 finance_app）
- /api/*（后挂载的 finance_app 兼容路径族）
"""

import pytest
from fastapi.testclient import TestClient

import server as finance_server


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


def test_simulation_current_account_without_owner_header_is_handled(
    client: TestClient,
) -> None:
    response = client.get("/api/simulation/accounts/current")

    assert 400 <= response.status_code < 500
    payload = response.json()
    # 证明路由已挂载：响应来自 simulation handler 的错误信封
    # {"error": {"code": ..., "message": ...}}，而非路由缺失时
    # Starlette/FastAPI 的裸 404（{"detail": "Not Found"}）。
    # 注意：现有实现（finance_god/api/simulation.py::_respond）将缺失
    # owner header 的 PermissionError 映射为 404/NOT_FOUND，语义上与
    # "路由缺失 404" 不同，此处通过错误信封与 message 内容区分。
    assert "error" in payload
    assert payload["error"]["code"] == "NOT_FOUND"
    assert "x-finance-god-owner-id" in payload["error"]["message"]


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
