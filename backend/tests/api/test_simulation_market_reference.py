from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from pydantic import BaseModel
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from finance_god.api.simulation import create_simulation_routes
from finance_god.domain import VersionReference

TRUSTED_VERSION = VersionReference(
    object_type="market_quote",
    object_id="000001.SZ",
    version="2026-07-24T15:00:00+08:00",
)


class _HistoricalBar(BaseModel):
    close: Decimal
    provider_time: str
    freshness: str


class _Execution:
    def __init__(self) -> None:
        self.created: dict[str, object] | None = None

    async def create_order_draft(self, **kwargs: object) -> dict[str, object]:
        self.created = kwargs
        return {"created": True}

    async def execute_immediate_market_order(self, **kwargs: object) -> dict[str, object]:
        self.created = kwargs
        return {"order_id": "order-1", "status": "filled"}


async def _owner(_request) -> str:
    return "user-1"


async def _trusted_reference(_symbol: str) -> tuple[Decimal, VersionReference]:
    return Decimal("11.10"), TRUSTED_VERSION


async def _historical_bars(_owner_id: str, _symbol: str) -> dict[str, object]:
    return {
        "bars": (
            _HistoricalBar(
                close=Decimal("11.10"),
                provider_time="2026-07-24T15:00:00+08:00",
                freshness="fresh",
            ),
        ),
        "frequency": "1m",
        "simulation_time": datetime.fromisoformat("2026-07-24T15:01:00+08:00"),
        "simulation_clock_revision": 3,
    }


async def _partially_failing_historical_bars(
    _owner_id: str,
    symbol: str,
) -> dict[str, object]:
    if symbol == "399001.SZ":
        raise ValueError("no completed PandaData minute bar is available")
    return await _historical_bars(_owner_id, symbol)


def _app(
    execution: _Execution,
    *,
    historical_market_bars_provider=None,
) -> Starlette:
    return Starlette(
        routes=[
            Mount(
                "/api/simulation",
                routes=create_simulation_routes(
                    execution=execution,
                    accounts=object(),
                    portfolio=object(),
                    decision_inbox=object(),
                    owner_resolver=_owner,
                    market_reference_provider=_trusted_reference,
                    historical_market_bars_provider=historical_market_bars_provider,
                ),
            )
        ]
    )


def _draft_body(*, price: str, version: str) -> dict[str, object]:
    return {
        "mode": "manual",
        "account_id": "account-1",
        "instrument_id": "000001.SZ",
        "side": "buy",
        "order_type": "market",
        "quantity": "100",
        "amount": None,
        "limit_price": None,
        "reference_price": price,
        "time_in_force": "day",
        "fund_rule_version": None,
        "valid_until": (datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
        "input_versions": [
            {
                "object_type": "market_quote",
                "object_id": "000001.SZ",
                "version": version,
            }
        ],
        "plan_reference": None,
    }


def test_draft_uses_the_server_market_reference() -> None:
    execution = _Execution()
    with TestClient(_app(execution)) as client:
        response = client.post(
            "/api/simulation/drafts",
            json=_draft_body(
                price="11.10",
                version=TRUSTED_VERSION.version,
            ),
            headers={"Idempotency-Key": "draft-trusted-1"},
        )

    assert response.status_code == 201
    assert execution.created is not None
    assert execution.created["reference_price"] == Decimal("11.10")
    assert execution.created["input_versions"] == (TRUSTED_VERSION,)


def test_draft_rejects_a_browser_price_that_no_longer_matches() -> None:
    execution = _Execution()
    with TestClient(_app(execution)) as client:
        response = client.post(
            "/api/simulation/drafts",
            json=_draft_body(
                price="9.99",
                version=TRUSTED_VERSION.version,
            ),
            headers={"Idempotency-Key": "draft-tampered-1"},
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    assert execution.created is None


def test_immediate_market_order_uses_only_the_server_quote() -> None:
    execution = _Execution()
    with TestClient(_app(execution)) as client:
        response = client.post(
            "/api/simulation/market-orders",
            json={
                "account_id": "account-1",
                "instrument_id": "000001.SZ",
                "side": "buy",
                "quantity": "100",
            },
            headers={"Idempotency-Key": "market-order-1"},
        )

    assert response.status_code == 201
    assert response.json()["status"] == "filled"
    assert execution.created is not None
    assert execution.created["trusted_price"] == Decimal("11.10")
    assert execution.created["market_evidence"] == TRUSTED_VERSION


def test_historical_overview_uses_provider_clock_revision() -> None:
    execution = _Execution()
    with TestClient(
        _app(
            execution,
            historical_market_bars_provider=_historical_bars,
        )
    ) as client:
        response = client.get(
            "/api/simulation/market/overview",
            params={"symbols": "000001.SZ"},
        )

    assert response.status_code == 200
    quote = response.json()["data"]["quotes"][0]
    assert quote["last"] == "11.10"
    assert quote["simulation_clock_revision"] == 3


def test_historical_overview_keeps_successful_quotes_when_one_symbol_fails() -> None:
    execution = _Execution()
    with TestClient(
        _app(
            execution,
            historical_market_bars_provider=_partially_failing_historical_bars,
        )
    ) as client:
        response = client.get(
            "/api/simulation/market/overview",
            params={"symbols": "000001.SZ,399001.SZ"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert [quote["symbol"] for quote in payload["data"]["quotes"]] == ["000001.SZ"]
    assert payload["warnings"] == [
        {
            "code": "HISTORICAL_MARKET_DATA_UNAVAILABLE",
            "symbol": "399001.SZ",
            "message": "该标的在当前模拟时点没有可展示的 PandaData 分钟行情",
        }
    ]


def test_historical_bars_serializes_simulation_time() -> None:
    execution = _Execution()
    with TestClient(
        _app(
            execution,
            historical_market_bars_provider=_historical_bars,
        )
    ) as client:
        response = client.get(
            "/api/simulation/market/bars",
            params={"symbol": "000001.SZ"},
        )

    assert response.status_code == 200
    assert response.json()["simulation_time"] == "2026-07-24T15:01:00+08:00"
