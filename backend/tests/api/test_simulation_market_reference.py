from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
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
DECISION_CONTEXT = {
    "thesis": "估值处于历史低位且盈利改善",
    "expected_return": "三个月目标收益 10%",
    "primary_risks": "盈利修复不及预期",
    "contrary_evidence": "行业净息差仍在收窄",
    "expected_holding_period": "三个月",
    "confidence": "中等",
}


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

    async def execute_immediate_market_order(
        self, **kwargs: object
    ) -> dict[str, object]:
        self.created = kwargs
        return {
            "order_id": "order-1",
            "status": "filled",
            "fills": [{"fill_id": "fill-order-1"}],
        }

    async def reconcile(self, **kwargs: object) -> object:
        self.created = kwargs
        return SimpleNamespace(order_id=str(kwargs["order_id"]))

    async def get_order_view(self, **kwargs: object) -> dict[str, object]:
        return {
            "order_id": str(kwargs["order_id"]),
            "status": "filled",
            "fills": [{"fill_id": f"fill-{kwargs['order_id']}"}],
        }


class _TradeReview:
    def __init__(self) -> None:
        self.projected_owner: str | None = None

    async def current_profile_version(self, *, owner_id: str) -> int:
        assert owner_id == "user-1"
        return 7

    async def project_execution_outbox(
        self,
        *,
        owner_id: str,
        fill_ids: frozenset[str],
    ) -> tuple:
        self.projected_owner = owner_id
        assert fill_ids
        return ()

    async def journal_for_order(
        self,
        *,
        owner_id: str,
        order_id: str,
    ) -> dict[str, object]:
        assert owner_id == "user-1"
        return {
            "episode_id": f"episode-{order_id}",
            "decision_snapshot_id": f"snapshot-{order_id}",
            "review_triggered": False,
        }


async def _owner(_request) -> str:
    return "user-1"


async def _trusted_reference(_symbol: str) -> tuple[Decimal, VersionReference]:
    return Decimal("11.10"), TRUSTED_VERSION


async def _historical_bars(
    _owner_id: str,
    _symbol: str,
    frequency: str,
) -> dict[str, object]:
    return {
        "bars": (
            _HistoricalBar(
                close=Decimal("11.10"),
                provider_time="2026-07-24T15:00:00+08:00",
                freshness="fresh",
            ),
        ),
        "frequency": "日频" if frequency == "daily" else "1m",
        "simulation_time": datetime.fromisoformat("2026-07-24T15:01:00+08:00"),
        "simulation_clock_revision": 3,
    }


async def _partially_failing_historical_bars(
    _owner_id: str,
    symbol: str,
    frequency: str,
) -> dict[str, object]:
    if symbol == "399001.SZ":
        raise ValueError("no completed PandaData minute bar is available")
    return await _historical_bars(_owner_id, symbol, frequency)


async def _failed_historical_bars(
    _owner_id: str,
    _symbol: str,
    _frequency: str,
) -> dict[str, object]:
    raise RuntimeError("upstream details must not leak")


def _app(
    execution: _Execution,
    *,
    historical_market_bars_provider=None,
    trade_review_service=None,
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
                    trade_review_service=trade_review_service,
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
                "decision_context": {
                    **DECISION_CONTEXT,
                    "thesis": "  估值处于历史低位且盈利改善  ",
                },
            },
            headers={"Idempotency-Key": "market-order-1"},
        )

    assert response.status_code == 201
    assert response.json()["status"] == "filled"
    assert execution.created is not None
    assert execution.created["trusted_price"] == Decimal("11.10")
    assert execution.created["market_evidence"] == TRUSTED_VERSION
    assert execution.created["decision_context"].thesis == "估值处于历史低位且盈利改善"


def test_immediate_market_order_binds_server_profile_version() -> None:
    execution = _Execution()
    trade_review = _TradeReview()
    with TestClient(_app(execution, trade_review_service=trade_review)) as client:
        response = client.post(
            "/api/simulation/market-orders",
            json={
                "account_id": "account-1",
                "instrument_id": "000001.SZ",
                "side": "buy",
                "quantity": "100",
                "decision_context": DECISION_CONTEXT,
            },
            headers={"Idempotency-Key": "profile-bound-order"},
        )

    assert response.status_code == 201
    assert execution.created is not None
    assert execution.created["submission_profile_version"] == 7
    assert trade_review.projected_owner == "user-1"
    assert response.json()["decision_snapshot_id"] == "snapshot-order-1"


def test_reconcile_projects_delayed_fill_through_the_same_outbox() -> None:
    execution = _Execution()
    trade_review = _TradeReview()
    with TestClient(_app(execution, trade_review_service=trade_review)) as client:
        response = client.post(
            "/api/simulation/orders/order-delayed/reconcile",
            json={},
            headers={"Idempotency-Key": "reconcile-delayed"},
        )

    assert response.status_code == 200
    assert trade_review.projected_owner == "user-1"
    assert response.json()["decision_snapshot_id"] == "snapshot-order-delayed"


@pytest.mark.parametrize("field_name", tuple(DECISION_CONTEXT))
def test_immediate_market_order_rejects_blank_decision_context(
    field_name: str,
) -> None:
    execution = _Execution()
    context = {**DECISION_CONTEXT, field_name: " \n\t "}
    with TestClient(_app(execution)) as client:
        response = client.post(
            "/api/simulation/market-orders",
            json={
                "account_id": "account-1",
                "instrument_id": "000001.SZ",
                "side": "buy",
                "quantity": "100",
                "decision_context": context,
            },
            headers={"Idempotency-Key": f"blank-{field_name}"},
        )

    assert response.status_code == 422
    assert execution.created is None


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


def test_historical_bars_passes_daily_frequency_to_provider() -> None:
    execution = _Execution()
    with TestClient(
        _app(
            execution,
            historical_market_bars_provider=_historical_bars,
        )
    ) as client:
        response = client.get(
            "/api/simulation/market/bars",
            params={"symbol": "000001.SZ", "frequency": "daily"},
        )

    assert response.status_code == 200
    assert response.json()["frequency"] == "日频"


def test_historical_bars_rejects_an_unknown_frequency() -> None:
    execution = _Execution()
    with TestClient(
        _app(
            execution,
            historical_market_bars_provider=_historical_bars,
        )
    ) as client:
        response = client.get(
            "/api/simulation/market/bars",
            params={"symbol": "000001.SZ", "frequency": "weekly"},
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_historical_bars_maps_upstream_failure_to_service_unavailable() -> None:
    execution = _Execution()
    with TestClient(
        _app(
            execution,
            historical_market_bars_provider=_failed_historical_bars,
        )
    ) as client:
        response = client.get(
            "/api/simulation/market/bars",
            params={"symbol": "000300.SH", "frequency": "daily"},
        )

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "SERVICE_UNAVAILABLE",
            "message": "当前模拟时点没有可展示的 PandaData K 线",
        }
    }
