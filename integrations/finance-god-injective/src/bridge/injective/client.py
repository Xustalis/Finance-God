from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol
from uuid import uuid4

from .models import ChainOrder, Market, OrderBook, WalletBalance


class InjectiveError(RuntimeError):
    pass


class AsyncClientV2(Protocol):
    async def composer(self) -> Any: ...
    async def current_chain_gas_price(self) -> int: ...
    async def fetch_account(self, address: str) -> Any: ...


class IndexerClient(Protocol):
    async def fetch_spot_markets(self, *args: Any, **kwargs: Any) -> Any: ...
    async def fetch_spot_orderbook_v2(self, *args: Any, **kwargs: Any) -> Any: ...
    async def fetch_subaccount_balances_list(self, *args: Any, **kwargs: Any) -> Any: ...
    async def fetch_spot_subaccount_orders_list(self, *args: Any, **kwargs: Any) -> Any: ...


@dataclass(frozen=True, slots=True)
class SpotLimitOrderRequest:
    market_id: str
    subaccount_id: str
    side: str
    price: Decimal
    quantity: Decimal
    client_order_id: str


def _value(value: Any, *names: str) -> Any:
    for name in names:
        if isinstance(value, dict) and name in value:
            return value[name]
        if hasattr(value, name):
            return getattr(value, name)
    return None


def _decimal(value: Any, label: str) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception as exc:
        raise InjectiveError(f"Injective returned invalid {label}") from exc


class InjectiveClient:
    """Injectable, Testnet-only façade over sdk-python's V2 chain client."""

    def __init__(
        self,
        client: AsyncClientV2,
        *,
        indexer: IndexerClient | None = None,
        network: str = "testnet",
        broadcast: Callable[[SpotLimitOrderRequest], Awaitable[str]] | None = None,
        cancel: Callable[[str, str, str], Awaitable[str]] | None = None,
        private_key_hex: str | None = None,
        subaccount_index: int = 0,
        sdk_network: Any | None = None,
    ) -> None:
        if network.lower() != "testnet":
            raise InjectiveError("only Injective Testnet is permitted")
        self._client = client
        self._indexer = indexer or client  # type: ignore[assignment]
        self._broadcast = broadcast
        self._cancel = cancel
        self._private_key_hex = private_key_hex
        self._sdk_network = sdk_network
        self.account_address: str | None = None
        self.subaccount_id = "execution-disabled"
        if private_key_hex:
            try:
                from pyinjective.wallet import PrivateKey

                address = PrivateKey.from_hex(private_key_hex).to_public_key().to_address()
                self.account_address = address.to_acc_bech32()
                self.subaccount_id = address.get_subaccount_id(index=subaccount_index)
            except Exception as exc:
                raise InjectiveError("invalid Injective Testnet private key") from exc

    @classmethod
    def from_sdk(
        cls,
        *,
        network: str = "testnet",
        private_key_hex: str | None = None,
        subaccount_index: int = 0,
    ) -> InjectiveClient:
        if network.lower() != "testnet":
            raise InjectiveError("only Injective Testnet is permitted")
        try:
            from pyinjective.async_client_v2 import AsyncClient
            from pyinjective.core.network import Network
            from pyinjective.indexer_client import IndexerClient as SDKIndexerClient
        except ImportError as exc:
            raise InjectiveError("injective-py==1.13.1 is required for chain access") from exc
        sdk_network = Network.testnet()
        return cls(
            AsyncClient(sdk_network),
            indexer=SDKIndexerClient(sdk_network),
            network=network,
            private_key_hex=private_key_hex,
            subaccount_index=subaccount_index,
            sdk_network=sdk_network,
        )

    async def resolve_market(self, ticker: str = "INJ/USDT") -> Market:
        try:
            response = await self._indexer.fetch_spot_markets(market_statuses=["active"])
            markets = _value(response, "markets") or []
            raw = next(m for m in markets if str(_value(m, "ticker")) == ticker)
            return Market(
                str(_value(raw, "market_id", "marketId")),
                ticker,
                str(_value(raw, "market_status", "status") or "active").lower(),
                _decimal(
                    _value(raw, "min_price_tick_size", "minPriceTickSize"),
                    "price tick",
                ),
                _decimal(
                    _value(raw, "min_quantity_tick_size", "minQuantityTickSize"),
                    "quantity step",
                ),
                str(_value(raw, "base_denom", "baseDenom")),
                str(_value(raw, "quote_denom", "quoteDenom")),
            )
        except (InjectiveError, StopIteration) as exc:
            raise InjectiveError(f"active spot market {ticker} was not found") from exc
        except Exception as exc:
            raise InjectiveError(f"failed to resolve spot market {ticker}: {exc}") from exc

    async def order_book(self, market_id: str) -> OrderBook:
        try:
            response = await self._indexer.fetch_spot_orderbook_v2(
                market_id=market_id,
                depth=20,
            )
            book = _value(response, "orderbook", "orderbook_v2") or response
            buys, sells = _value(book, "buys") or [], _value(book, "sells") or []
            if not buys or not sells:
                raise InjectiveError("order book has no two-sided liquidity")
            return OrderBook(
                market_id,
                _decimal(_value(buys[0], "price"), "best bid"),
                _decimal(_value(sells[0], "price"), "best ask"),
            )
        except InjectiveError:
            raise
        except Exception as exc:
            raise InjectiveError(f"failed to read order book: {exc}") from exc

    async def balances(self, subaccount_id: str) -> list[WalletBalance]:
        try:
            response = await self._indexer.fetch_subaccount_balances_list(
                subaccount_id=subaccount_id
            )
            rows = _value(response, "balances") or []
            return [
                WalletBalance(
                    subaccount_id,
                    str(_value(row, "denom")),
                    _decimal(
                        _value(row, "available_balance", "availableBalance"),
                        "available balance",
                    ),
                )
                for row in rows
            ]
        except Exception as exc:
            raise InjectiveError(f"failed to read balances: {exc}") from exc

    async def submit_limit_order(self, request: SpotLimitOrderRequest) -> str:
        if request.side not in {"buy", "sell"} or request.price <= 0 or request.quantity <= 0:
            raise InjectiveError("invalid spot GTC limit order")
        if self._broadcast is None:
            return await self._submit_with_sdk(request)
        try:
            return await self._broadcast(request)
        except Exception as exc:
            raise InjectiveError(f"spot order broadcast failed: {exc}") from exc

    async def cancel_order(self, market_id: str, subaccount_id: str, order_hash: str) -> str:
        if not order_hash:
            raise InjectiveError("order_hash is required")
        if self._cancel is None:
            return await self._cancel_with_sdk(market_id, subaccount_id, order_hash)
        try:
            return await self._cancel(market_id, subaccount_id, order_hash)
        except Exception as exc:
            raise InjectiveError(f"spot order cancellation failed: {exc}") from exc

    async def orders(self, market_id: str, subaccount_id: str) -> list[ChainOrder]:
        try:
            response = await self._indexer.fetch_spot_subaccount_orders_list(
                subaccount_id=subaccount_id,
                market_id=market_id,
            )
            rows = _value(response, "orders") or []
            return [
                ChainOrder(
                    str(_value(row, "order_hash", "orderHash")),
                    str(_value(row, "state", "status") or "unknown").lower(),
                    _decimal(
                        _value(row, "filled_quantity", "filledQuantity") or "0",
                        "filled quantity",
                    ),
                    _value(row, "tx_hash", "txHash"),
                    _value(row, "cid", "client_order_id", "clientOrderId"),
                )
                for row in rows
            ]
        except Exception as exc:
            raise InjectiveError(f"failed to query orders: {exc}") from exc

    async def close(self) -> None:
        """Close SDK gRPC channels on the same event loop that created them."""
        for client, method_names in (
            (self._indexer, ("close_exchange_channel", "close_explorer_channel")),
            (self._client, ("close_chain_channel", "close_chain_stream_channel")),
        ):
            for method_name in method_names:
                close = getattr(client, method_name, None)
                if close is not None:
                    await close()

    async def _submit_with_sdk(self, request: SpotLimitOrderRequest) -> str:
        broadcaster, composer = await self._sdk_broadcaster()
        assert self.account_address is not None
        message = composer.msg_create_spot_limit_order(
            sender=self.account_address,
            market_id=request.market_id,
            subaccount_id=request.subaccount_id,
            fee_recipient=self.account_address,
            price=request.price,
            quantity=request.quantity,
            order_type=request.side.upper(),
            cid=request.client_order_id or str(uuid4()),
        )
        return await self._broadcast_messages(broadcaster, [message])

    async def _cancel_with_sdk(
        self,
        market_id: str,
        subaccount_id: str,
        order_hash: str,
    ) -> str:
        broadcaster, composer = await self._sdk_broadcaster()
        assert self.account_address is not None
        message = composer.msg_cancel_spot_order(
            sender=self.account_address,
            market_id=market_id,
            subaccount_id=subaccount_id,
            order_hash=order_hash,
        )
        return await self._broadcast_messages(broadcaster, [message])

    async def _sdk_broadcaster(self) -> tuple[Any, Any]:
        if not self._private_key_hex or not self.account_address or self._sdk_network is None:
            raise InjectiveError("no Testnet signer/broadcaster configured")
        try:
            from pyinjective.core.broadcaster import MsgBroadcasterWithPk

            await self._client.fetch_account(self.account_address)
            composer = await self._client.composer()
            gas_price = int((await self._client.current_chain_gas_price()) * 1.1)
            broadcaster = MsgBroadcasterWithPk.new_using_simulation(
                network=self._sdk_network,
                private_key=self._private_key_hex,
                gas_price=gas_price,
                client=self._client,
                composer=composer,
            )
            return broadcaster, composer
        except InjectiveError:
            raise
        except Exception as exc:
            raise InjectiveError(f"failed to initialize Testnet signer: {exc}") from exc

    @staticmethod
    async def _broadcast_messages(broadcaster: Any, messages: list[Any]) -> str:
        try:
            result = await broadcaster.broadcast(messages)
        except Exception as exc:
            raise InjectiveError(f"Testnet transaction broadcast failed: {exc}") from exc
        if not isinstance(result, dict):
            raise InjectiveError("Injective broadcast returned an invalid response")
        code = result.get("code")
        if code not in (None, 0, "0"):
            message = result.get("raw_log") or result.get("message") or "rejected"
            raise InjectiveError(f"Injective rejected transaction: {message}")
        tx_hash = result.get("txhash") or result.get("tx_hash") or result.get("hash")
        if not isinstance(tx_hash, str) or not tx_hash:
            raise InjectiveError("Injective broadcast returned no transaction hash")
        return tx_hash
