from __future__ import annotations

import asyncio
import json

import server
from finance_god.market_data import ErrorKind, MarketDataError
from starlette.requests import Request


class FailingCoordinator:
    async def get(self, symbols: object) -> object:
        del symbols
        raise MarketDataError(
            ErrorKind.PERMISSION,
            "Bearer secret-token denied at https://private.example.test/data",
            endpoint="get_stock_rt_daily",
        )


class StubService:
    def fetch_bars(self, symbol: str, *, limit: int) -> object:
        del symbol, limit
        raise RuntimeError("password=should-never-reach-browser")

    def catalog(self) -> tuple[object, ...]:
        return ()

    def probe_readiness(self) -> tuple[bool, str]:
        return False, "MARKET_DATA_DEPENDENCY_UNAVAILABLE"


def test_market_api_returns_stable_safe_errors_without_raw_exception_text(
    monkeypatch,
) -> None:
    monkeypatch.setattr(server, "market_data", StubService())
    monkeypatch.setattr(server, "quote_coordinator", FailingCoordinator())
    quotes = asyncio.run(
        server.quotes(_request(b"symbols=000001.SZ"))
    )
    bars = asyncio.run(
        server.bars(_request(b"symbol=000001.SZ"))
    )
    invalid = asyncio.run(
        server.bars(_request(b"symbol=000001.SZ&limit=bad"))
    )
    health = asyncio.run(server.health(_request(b"")))
    quote_payload = json.loads(quotes.body)
    bars_payload = json.loads(bars.body)
    invalid_payload = json.loads(invalid.body)
    health_payload = json.loads(health.body)
    rendered = json.dumps(
        [quote_payload, bars_payload, invalid_payload],
        ensure_ascii=False,
    )

    assert quotes.status_code == 502
    assert quote_payload["error"]["code"] == "MARKET_DATA_PERMISSION_DENIED"
    assert bars.status_code == 500
    assert bars_payload["error"]["code"] == "MARKET_DATA_INTERNAL_ERROR"
    assert invalid.status_code == 400
    assert invalid_payload["error"]["code"] == "MARKET_DATA_INVALID_REQUEST"
    assert health.status_code == 503
    assert health_payload["liveness"] == "live"
    assert health_payload["readiness"] == "not_ready"
    assert "secret-token" not in rendered
    assert "private.example.test" not in rendered
    assert "should-never-reach-browser" not in rendered
    assert all(
        len(payload["error"]["trace_id"]) == 32
        for payload in (quote_payload, bars_payload, invalid_payload)
    )


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
