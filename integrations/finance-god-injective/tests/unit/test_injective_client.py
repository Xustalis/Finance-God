from decimal import Decimal

import pytest

from bridge.injective.client import InjectiveClient, InjectiveError, SpotLimitOrderRequest


class FakeClient:
    async def fetch_spot_markets(self, **kwargs):
        return {
            "markets": [
                {
                    "market_id": "m",
                    "ticker": "INJ/USDT",
                    "market_status": "active",
                    "min_price_tick_size": "0.01",
                    "min_quantity_tick_size": "0.1",
                    "base_denom": "inj",
                    "quote_denom": "usdt",
                }
            ]
        }

    async def fetch_spot_orderbook_v2(self, **kwargs):
        return {"orderbook": {"buys": [{"price": "10"}], "sells": [{"price": "11"}]}}

    async def fetch_subaccount_balances_list(self, **kwargs):
        return {"balances": [{"denom": "usdt", "available_balance": "25"}]}

    async def fetch_spot_subaccount_orders_list(self, **kwargs):
        return {"orders": [{"order_hash": "o", "state": "booked", "filled_quantity": "0"}]}


@pytest.mark.asyncio
async def test_dynamic_reads_and_injected_broadcast() -> None:
    sent: list[SpotLimitOrderRequest] = []

    async def broadcast(request: SpotLimitOrderRequest) -> str:
        sent.append(request)
        return "tx"

    adapter = InjectiveClient(FakeClient(), broadcast=broadcast)
    market = await adapter.resolve_market()
    assert market.market_id == "m"
    assert (await adapter.order_book("m")).best_ask == Decimal("11")
    assert (await adapter.balances("sub"))[0].available == Decimal("25")
    assert (await adapter.orders("m", "sub"))[0].order_hash == "o"
    assert (
        await adapter.submit_limit_order(
            SpotLimitOrderRequest(
                "m",
                "sub",
                "buy",
                Decimal("10"),
                Decimal("1"),
                "cid-1",
            )
        )
        == "tx"
    )
    assert sent


def test_mainnet_and_unsigner_are_explicit() -> None:
    with pytest.raises(InjectiveError):
        InjectiveClient(FakeClient(), network="mainnet")


@pytest.mark.asyncio
async def test_submit_without_private_key_is_explicit() -> None:
    adapter = InjectiveClient(FakeClient())
    with pytest.raises(InjectiveError, match="no Testnet signer"):
        await adapter.submit_limit_order(
            SpotLimitOrderRequest(
                "m",
                "sub",
                "buy",
                Decimal("10"),
                Decimal("1"),
                "cid-1",
            )
        )
