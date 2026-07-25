from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Market:
    market_id: str
    ticker: str
    status: str
    min_price_tick_size: Decimal
    min_quantity_tick_size: Decimal
    base_denom: str
    quote_denom: str


@dataclass(frozen=True, slots=True)
class OrderBook:
    market_id: str
    best_bid: Decimal
    best_ask: Decimal


@dataclass(frozen=True, slots=True)
class WalletBalance:
    subaccount_id: str
    denom: str
    available: Decimal


@dataclass(frozen=True, slots=True)
class ChainOrder:
    order_hash: str
    status: str
    filled_quantity: Decimal
    tx_hash: str | None = None
    client_order_id: str | None = None
