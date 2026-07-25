from __future__ import annotations

import time
from decimal import Decimal

from fastapi.testclient import TestClient
from pydantic import SecretStr

from bridge.injective import ChainOrder, Market, OrderBook, WalletBalance
from bridge.main import create_app
from bridge.settings import Settings


class FakeInjective:
    account_address = "inj1test"
    subaccount_id = "0xsubaccount"

    def __init__(self) -> None:
        self.client_order_id: str | None = None

    async def resolve_market(self, ticker: str) -> Market:
        return Market(
            market_id="market-1",
            ticker=ticker,
            status="active",
            min_price_tick_size=Decimal("0.01"),
            min_quantity_tick_size=Decimal("0.1"),
            base_denom="inj",
            quote_denom="usdt",
        )

    async def order_book(self, market_id: str) -> OrderBook:
        return OrderBook(
            market_id=market_id,
            best_bid=Decimal("10.00"),
            best_ask=Decimal("10.20"),
        )

    async def balances(self, subaccount_id: str) -> list[WalletBalance]:
        return [
            WalletBalance(subaccount_id, "usdt", Decimal("25")),
            WalletBalance(subaccount_id, "inj", Decimal("2")),
        ]

    async def submit_limit_order(self, request) -> str:
        self.client_order_id = request.client_order_id
        return "tx-create-1"

    async def orders(self, market_id: str, subaccount_id: str) -> list[ChainOrder]:
        if self.client_order_id is None:
            return []
        return [
            ChainOrder(
                order_hash="order-hash-1",
                status="booked",
                filled_quantity=Decimal("0"),
                tx_hash="tx-create-1",
                client_order_id=self.client_order_id,
            )
        ]

    async def cancel_order(
        self,
        market_id: str,
        subaccount_id: str,
        order_hash: str,
    ) -> str:
        return "tx-cancel-1"


def _headers(key: str) -> dict[str, str]:
    return {
        "Authorization": "Bearer admin-test-token",
        "Idempotency-Key": key,
    }


def test_plan_review_confirm_submit_and_reconcile() -> None:
    settings = Settings(
        _env_file=None,
        BRIDGE_DATABASE_URL="sqlite+aiosqlite:///:memory:",
        BRIDGE_ADMIN_TOKEN="admin-test-token",
        BRIDGE_AUTO_CREATE_SCHEMA=True,
        BRIDGE_RECONCILIATION_INTERVAL_SECONDS=1,
        INJECTIVE_PRIVATE_KEY_HEX=SecretStr("11" * 32),
    )
    app = create_app(settings=settings, injective=FakeInjective())

    with TestClient(app) as client:
        assert client.get("/live").json() == {"status": "live"}
        ready = client.get("/ready")
        assert ready.status_code == 200
        assert ready.json()["execution_ready"] is True

        unauthenticated = client.post(
            "/v1/plans",
            headers={"Idempotency-Key": "unauthenticated"},
            json={"side": "buy", "price": "10.00", "quantity": "1.0"},
        )
        assert unauthenticated.status_code == 401

        created = client.post(
            "/v1/plans",
            headers=_headers("plan-create-1"),
            json={"side": "buy", "price": "10.00", "quantity": "1.0"},
        )
        assert created.status_code == 201
        plan_id = created.json()["id"]

        replay = client.post(
            "/v1/plans",
            headers=_headers("plan-create-1"),
            json={"side": "buy", "price": "10.00", "quantity": "1.0"},
        )
        assert replay.status_code == 201
        assert replay.json()["id"] == plan_id

        reviewed = client.post(
            f"/v1/plans/{plan_id}/review",
            headers=_headers("plan-review-1"),
        )
        assert reviewed.status_code == 200, reviewed.text
        assert reviewed.json()["status"] == "reviewed", reviewed.json()["risk_report"]["violations"]
        assert reviewed.json()["risk_report"]["passed"] is True

        confirmed = client.post(
            f"/v1/plans/{plan_id}/confirm",
            headers=_headers("plan-confirm-1"),
            json={"expected_revision": reviewed.json()["revision"]},
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["status"] == "confirmed"

        deadline = time.monotonic() + 3
        page = None
        while time.monotonic() < deadline:
            page = client.get(f"/v1/plans/{plan_id}").json()
            if page["order"] and page["order"]["status"] == "open":
                break
            time.sleep(0.05)

        assert page is not None
        assert page["plan"]["status"] == "submitted"
        assert page["order"]["tx_hash"] == "tx-create-1"
        assert page["order"]["order_hash"] == "order-hash-1"
        assert page["order"]["status"] == "open"
