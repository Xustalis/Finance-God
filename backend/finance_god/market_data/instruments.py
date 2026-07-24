"""Authoritative instrument-master and alias resolution."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from hashlib import sha256
import json
from types import MappingProxyType

from .contracts import AssetClass, InstrumentId, MarketType


class UnknownInstrumentError(ValueError):
    """Raised when a symbol is absent from the instrument master."""


class InstrumentMaster:
    """Immutable canonical/alias index; no suffix-based asset guessing."""

    def __init__(
        self,
        instruments: Iterable[InstrumentId],
        *,
        identity: str = "finance-god-instrument-master",
    ) -> None:
        by_alias: dict[str, InstrumentId] = {}
        by_symbol: dict[str, InstrumentId] = {}
        for instrument in instruments:
            canonical = instrument.symbol.strip().upper()
            if canonical in by_symbol:
                raise ValueError(f"duplicate canonical instrument: {canonical}")
            by_symbol[canonical] = instrument
            for alias in (canonical, instrument.provider_symbol, *instrument.aliases):
                key = alias.strip().upper()
                existing = by_alias.get(key)
                if existing is not None and existing.symbol != canonical:
                    raise ValueError(f"ambiguous instrument alias: {key}")
                by_alias[key] = instrument
        if not by_symbol:
            raise ValueError("instrument master cannot be empty")
        self._by_alias: Mapping[str, InstrumentId] = MappingProxyType(by_alias)
        self._by_symbol: Mapping[str, InstrumentId] = MappingProxyType(by_symbol)
        self._identity = identity
        material = [
            by_symbol[symbol].model_dump(mode="json") for symbol in sorted(by_symbol)
        ]
        self._version = sha256(
            json.dumps(
                material,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

    @property
    def identity(self) -> str:
        return self._identity

    @property
    def version(self) -> str:
        return self._version

    def resolve(self, value: str) -> InstrumentId:
        key = value.strip().upper()
        if not key:
            raise UnknownInstrumentError("instrument identifier cannot be blank")
        instrument = self._by_alias.get(key)
        if instrument is None:
            raise UnknownInstrumentError(
                f"instrument is not present in the authoritative master: {key}"
            )
        return instrument

    def all(self) -> tuple[InstrumentId, ...]:
        return tuple(self._by_symbol[symbol] for symbol in sorted(self._by_symbol))


DEFAULT_INSTRUMENT_MASTER = InstrumentMaster(
    (
        InstrumentId(
            symbol="000001.SZ",
            provider_symbol="000001.SZ",
            market=MarketType.CN,
            asset_class=AssetClass.EQUITY,
            currency="CNY",
            aliases=("SZ000001",),
        ),
        InstrumentId(
            symbol="600519.SH",
            provider_symbol="600519.SH",
            market=MarketType.CN,
            asset_class=AssetClass.EQUITY,
            currency="CNY",
            aliases=("SH600519",),
        ),
        InstrumentId(
            symbol="000300.SH",
            provider_symbol="000300.SH",
            market=MarketType.CN,
            asset_class=AssetClass.INDEX,
            currency="CNY",
            aliases=("CSI300",),
        ),
        InstrumentId(
            symbol="510300.SH",
            provider_symbol="510300.SH",
            market=MarketType.CN,
            asset_class=AssetClass.ETF,
            currency="CNY",
            aliases=("SH510300",),
        ),
        InstrumentId(
            symbol="161725.SZ",
            provider_symbol="161725.SZ",
            market=MarketType.CN,
            asset_class=AssetClass.LOF,
            currency="CNY",
            aliases=("SZ161725",),
        ),
        InstrumentId(
            symbol="159915.SZ",
            provider_symbol="159915.SZ",
            market=MarketType.CN,
            asset_class=AssetClass.ETF,
            currency="CNY",
            aliases=("SZ159915",),
        ),
        InstrumentId(
            symbol="000001.OF",
            provider_symbol="000001.OF",
            market=MarketType.CN,
            asset_class=AssetClass.FUND,
            currency="CNY",
        ),
        InstrumentId(
            symbol="00700.HK",
            provider_symbol="00700.HK",
            market=MarketType.HK,
            asset_class=AssetClass.EQUITY,
            currency="HKD",
            aliases=("700.HK", "HK00700"),
        ),
        InstrumentId(
            symbol="AAPL.US",
            provider_symbol="AAPL",
            market=MarketType.US,
            asset_class=AssetClass.EQUITY,
            currency="USD",
            aliases=("AAPL", "US:AAPL"),
        ),
    )
)

DEFAULT_INSTRUMENT_MASTER_IDENTITY = DEFAULT_INSTRUMENT_MASTER.identity
DEFAULT_INSTRUMENT_MASTER_VERSION = DEFAULT_INSTRUMENT_MASTER.version
