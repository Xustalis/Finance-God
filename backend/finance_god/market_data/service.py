"""Compatibility façade over the normalized PandaData fact source."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from decimal import Decimal
from time import monotonic
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from .adapter import PandaCredentials, PandaDataAdapter
from .capabilities import EXPECTED_SDK_VERSION
from .contracts import (
    DataCategory,
    DataDiagnostic,
    DataEnvelope,
    DataFrequency,
    InstrumentId,
    MarketType,
    NormalizedBar,
    NormalizedSnapshot,
)
from .coordinator import SnapshotCoordinator
from .errors import (
    MarketDataConfigurationError,
    MarketDataError,
    MarketDataResponseError,
)
from .instruments import DEFAULT_INSTRUMENT_MASTER, InstrumentMaster
from .quality import (
    AuditedDQWorkflowPort,
    DQTrigger,
    DQTriggerResult,
    InMemoryDQTriggerRepository,
    InMemoryScopeFreezeRepository,
    QualityDecision,
    QualityGate,
    ScopeFreezeRecord,
)
from .release import (
    FailClosedPublishedState,
    PandaCalendarPublishedState,
    PublishedStatePort,
)
from .transport import InjectedSDKTransportPolicy

_UTC = ZoneInfo("UTC")


class MarketQuote(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    name: str
    asset_type: str
    market: str
    currency: str
    last: Decimal
    open: Decimal
    high: Decimal
    low: Decimal
    previous_close: Decimal | None
    change: Decimal | None
    change_percent: Decimal | None
    volume: Decimal
    amount: Decimal | None
    provider: str = "PandaData"
    provider_time: str
    retrieved_at: datetime
    frequency: str
    freshness: str
    market_status: str
    source_endpoint: str
    capability_version: str
    trade_eligible: Literal[False] = False


class MarketBar(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    time: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    amount: Decimal | None = None
    freshness: str
    provider_time: str
    trade_eligible: Literal[False] = False


class QuoteBatch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str = "PandaData"
    requested_at: datetime
    cache_hit: bool
    quotes: tuple[MarketQuote, ...]
    errors: dict[str, str]
    diagnostics: tuple[DataDiagnostic, ...] = ()
    quality: dict[str, QualityDecision] = Field(default_factory=dict)
    trade_eligible: Literal[False] = False


class MarketDataService:
    """Thin application adapter; all facts and policy live in PandaDataAdapter."""

    def __init__(
        self,
        *,
        adapter: PandaDataAdapter | None = None,
        instrument_master: InstrumentMaster = DEFAULT_INSTRUMENT_MASTER,
        sdk: Any | None = None,
        sdk_version: str = EXPECTED_SDK_VERSION,
        username: str | None = None,
        password: str | None = None,
        base_url: str | None = None,
        now: Callable[[], datetime] | None = None,
        clock: Callable[[], float] = monotonic,
        published_state: PublishedStatePort | None = None,
        quality_gate: QualityGate | None = None,
        dq_trigger: DQTrigger | None = None,
    ) -> None:
        del clock
        if adapter is None:
            if sdk is None:
                raise MarketDataConfigurationError(
                    "PandaDataAdapter or injected SDK is required"
                )
            adapter = PandaDataAdapter(
                sdk=sdk,
                sdk_version=sdk_version,
                credentials=PandaCredentials(
                    username=username or "",
                    password=password or "",
                    base_url=base_url,
                ),
                transport_policy=InjectedSDKTransportPolicy(),
                now=now,
            )
        self._adapter = adapter
        self._master = instrument_master
        self._now = now or (lambda: datetime.now(_UTC))
        self._published_state = published_state or FailClosedPublishedState()
        self._quality_gate = quality_gate or QualityGate(
            InMemoryScopeFreezeRepository()
        )
        self._dq_workflow = AuditedDQWorkflowPort()
        self._dq_trigger = dq_trigger or DQTrigger(
            InMemoryDQTriggerRepository(),
            self._dq_workflow,
        )
        self._latest_quality: dict[str, QualityDecision] = {}
        self._latest_dq_trigger: dict[str, DQTriggerResult] = {}

    @classmethod
    def from_environment(cls) -> MarketDataService:
        adapter = PandaDataAdapter.from_environment()
        return cls(
            adapter=adapter,
            published_state=PandaCalendarPublishedState(adapter),
        )

    @property
    def instrument_master(self) -> InstrumentMaster:
        return self._master

    def resolve(self, symbol: str) -> InstrumentId:
        return self._master.resolve(symbol)

    def fetch_snapshot(
        self, instrument: InstrumentId
    ) -> DataEnvelope[NormalizedSnapshot]:
        observed_at = self._aware_now()
        trading_date = observed_at.astimezone(
            _market_zone(instrument.market)
        ).strftime("%Y%m%d")
        publication = self._published_state.evaluate(
            instrument=instrument,
            category=DataCategory.SNAPSHOT,
            frequency=DataFrequency.SNAPSHOT,
            trading_date=trading_date,
            observed_at=observed_at,
        )
        envelope = self._adapter.fetch_snapshot(
            instrument,
            release_state=publication.state,
            expected_date=publication.trading_date,
            provider_published_at=publication.provider_published_at,
        )
        self._evaluate_quality(envelope, instrument.symbol)
        return envelope

    def fetch_quotes(self, symbols: Iterable[str]) -> QuoteBatch:
        requested = _bounded_symbols(symbols)
        quotes: list[MarketQuote] = []
        diagnostics: list[DataDiagnostic] = []
        errors: dict[str, str] = {}
        quality: dict[str, QualityDecision] = {}
        for symbol in requested:
            instrument = self.resolve(symbol)
            try:
                envelope = self.fetch_snapshot(instrument)
            except MarketDataError as error:
                errors[instrument.symbol] = str(error)
                continue
            diagnostics.extend(envelope.diagnostics)
            quality[instrument.symbol] = self._latest_quality[instrument.symbol]
            if envelope.items:
                quotes.append(_quote(envelope.items[0]))
            elif envelope.diagnostics:
                errors[instrument.symbol] = envelope.diagnostics[-1].message
        return QuoteBatch(
            requested_at=self._aware_now(),
            cache_hit=False,
            quotes=tuple(quotes),
            errors=errors,
            diagnostics=tuple(diagnostics),
            quality=quality,
        )

    def fetch_bars(
        self, symbol: str, *, limit: int = 80
    ) -> tuple[str, tuple[MarketBar, ...]]:
        instrument = self.resolve(symbol)
        now = self._aware_now()
        market_today = now.astimezone(_market_zone(instrument.market))
        if (
            instrument.market is MarketType.CN
            and instrument.asset_class.value == "equity"
        ):
            frequency = DataFrequency.MINUTE_1
            start = end = market_today.strftime("%Y%m%d")
        else:
            frequency = DataFrequency.DAILY
            end = market_today.strftime("%Y%m%d")
            start = (market_today - timedelta(days=120)).strftime("%Y%m%d")
        publication = self._published_state.evaluate(
            instrument=instrument,
            category=DataCategory.BAR,
            frequency=frequency,
            trading_date=end,
            observed_at=now,
        )
        envelope = self._adapter.fetch_bars(
            instrument,
            frequency=frequency,
            start_date=start,
            end_date=end,
            limit=limit,
            release_state=publication.state,
            provider_published_at=publication.provider_published_at,
        )
        self._evaluate_quality(
            envelope,
            f"{instrument.symbol}:{frequency.value}",
        )
        if not envelope.items:
            message = (
                envelope.diagnostics[-1].message
                if envelope.diagnostics
                else "PandaData returned no normalized bars"
            )
            raise MarketDataResponseError(message)
        return _display_frequency(frequency), tuple(_bar(item) for item in envelope.items)

    def catalog(self) -> tuple[dict[str, object], ...]:
        return self._adapter.catalog()

    def probe_readiness(self) -> tuple[bool, str]:
        try:
            self._published_state.probe(self._aware_now())
        except MarketDataError as error:
            return False, error.public_code.value
        return True, "ready"

    def resolve_quality_freeze(
        self,
        *,
        envelope: DataEnvelope[Any],
        affected_scope: str,
        expected_freeze_version: int,
        reason: str,
    ) -> ScopeFreezeRecord:
        return self._quality_gate.resolve_clean_envelope(
            envelope=envelope,
            affected_scope=affected_scope,
            expected_freeze_version=expected_freeze_version,
            reason=reason,
        )

    def quality_for(
        self,
        scopes: Iterable[str],
    ) -> dict[str, QualityDecision]:
        return {
            scope: self._latest_quality[scope]
            for scope in scopes
            if scope in self._latest_quality
        }

    def dq_trigger_for(self, scope: str) -> DQTriggerResult | None:
        return self._latest_dq_trigger.get(scope)

    def dq_audit_requests(self) -> tuple[object, ...]:
        return self._dq_workflow.list_requests()

    def _evaluate_quality(
        self,
        envelope: DataEnvelope[Any],
        affected_scope: str,
    ) -> QualityDecision:
        decision = self._quality_gate.evaluate(
            envelope,
            affected_scope=affected_scope,
        )
        self._latest_quality[affected_scope] = decision
        result = self._dq_trigger.trigger(
            decision,
            source_workflow="market_data",
        )
        self._latest_dq_trigger[affected_scope] = result
        return decision

    def _aware_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            raise ValueError("service clock must return timezone-aware datetime")
        return value.astimezone(_UTC)


class QuoteCoordinator:
    """Compatibility batch API backed by the per-symbol shared coordinator."""

    def __init__(
        self,
        service: MarketDataService,
        *,
        refresh_after_seconds: float = 0.9,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._service = service
        self._coordinator = SnapshotCoordinator(
            service.fetch_snapshot,
            refresh_after_seconds=refresh_after_seconds,
            clock=clock,
        )
        self._seen: set[str] = set()

    async def get(self, symbols: Iterable[str]) -> QuoteBatch:
        requested = _bounded_symbols(symbols)
        instruments = tuple(self._service.resolve(symbol) for symbol in requested)
        cache_hit = all(item.symbol in self._seen for item in instruments)
        result = await self._coordinator.get(instruments)
        successful = {item.instrument.symbol for item in result.items}
        self._seen.update(successful)
        errors = {
            item.scope.split(":", maxsplit=1)[0]: item.message
            for item in result.diagnostics
        }
        return QuoteBatch(
            requested_at=datetime.now(_UTC),
            cache_hit=cache_hit,
            quotes=tuple(_quote(item) for item in result.items),
            errors=errors,
            diagnostics=result.diagnostics,
            quality=self._service.quality_for(
                item.symbol for item in instruments
            ),
        )


def _quote(item: NormalizedSnapshot) -> MarketQuote:
    previous_close = item.previous_close
    change = (
        item.last - previous_close
        if previous_close is not None and previous_close != Decimal(0)
        else None
    )
    percent = (
        change / previous_close
        if change is not None
        and previous_close is not None
        and previous_close != Decimal(0)
        else None
    )
    return MarketQuote(
        symbol=item.instrument.symbol,
        name=item.instrument.symbol,
        asset_type=item.instrument.asset_class.value,
        market=item.instrument.market.value,
        currency=item.instrument.currency,
        last=item.last,
        open=item.open,
        high=item.high,
        low=item.low,
        previous_close=item.previous_close,
        change=change,
        change_percent=percent,
        volume=item.volume,
        amount=item.amount,
        provider_time=item.source.data_time.isoformat(),
        retrieved_at=item.source.ingested_at,
        frequency=item.source.frequency.value,
        freshness=item.freshness.status.value,
        market_status=item.freshness.release_state.value,
        source_endpoint=item.source.endpoint,
        capability_version=item.source.capability_version,
    )


def _bar(item: NormalizedBar) -> MarketBar:
    return MarketBar(
        time=item.source.data_time.isoformat(),
        open=item.open,
        high=item.high,
        low=item.low,
        close=item.close,
        volume=item.volume,
        amount=item.amount,
        freshness=item.freshness.status.value,
        provider_time=item.source.data_time.isoformat(),
    )


def _bounded_symbols(symbols: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw in symbols:
        symbol = raw.strip().upper()
        if not symbol:
            continue
        if len(symbol) > 32:
            raise ValueError("instrument identifier is too long")
        if symbol not in normalized:
            normalized.append(symbol)
    if not normalized:
        raise ValueError("at least one instrument is required")
    if len(normalized) > 40:
        raise ValueError("at most 40 instruments are allowed")
    return tuple(normalized)


def _display_frequency(frequency: DataFrequency) -> str:
    return {
        DataFrequency.MINUTE_1: "1分钟",
        DataFrequency.DAILY: "日频",
        DataFrequency.SNAPSHOT: "快照",
        DataFrequency.EVENT: "事件",
        DataFrequency.STATIC: "静态",
    }[frequency]


def _market_zone(market: MarketType) -> ZoneInfo:
    return {
        MarketType.CN: ZoneInfo("Asia/Shanghai"),
        MarketType.HK: ZoneInfo("Asia/Hong_Kong"),
        MarketType.US: ZoneInfo("America/New_York"),
    }[market]
