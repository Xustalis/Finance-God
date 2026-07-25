"""Compatibility façade over the normalized PandaData fact source."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from time import monotonic, time
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from .adapter import PandaCredentials, PandaDataAdapter
from .bar_cache import PersistentBarCache
from .capabilities import EXPECTED_SDK_VERSION
from .contracts import (
    DataCategory,
    DataDiagnostic,
    DataEnvelope,
    DataFrequency,
    DiagnosticCode,
    EmptyMeaning,
    InstrumentId,
    MarketType,
    MonitorDataset,
    NormalizedBar,
    NormalizedFact,
    NormalizedSnapshot,
    ReleaseState,
)
from .coordinator import SnapshotCoordinator
from .errors import (
    ErrorKind,
    MarketDataConfigurationError,
    MarketDataError,
    MarketDataResponseError,
)
from .instruments import (
    DEFAULT_INSTRUMENT_MASTER,
    InstrumentMaster,
    UnknownInstrumentError,
)
from .quality import (
    DQTriggerRequest,
    DQWorkflowPort,
    InMemoryScopeFreezeRepository,
    QualityContext,
    QualityDecision,
    QualityGate,
    ScopeFreezeRecord,
    build_dq_trigger_request,
)
from .release import (
    FailClosedPublishedState,
    PandaCalendarPublishedState,
    PublishedStatePort,
)
from .transport import InjectedSDKTransportPolicy

_UTC = ZoneInfo("UTC")
_READINESS_CANARY_SYMBOL = "000001.SZ"
_READINESS_CACHE_SECONDS = 30.0


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
    session_alignment: Literal[
        "current_session", "latest_released_session"
    ] = "current_session"
    market_status: str
    source_endpoint: str
    capability_version: str
    instrument_master_identity: str
    instrument_master_version: str
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
    source_endpoint: str
    capability_version: str
    instrument_master_identity: str
    instrument_master_version: str
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


class QualityOutcome(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: QualityDecision
    dq_request: DQTriggerRequest | None


class MarketBarsResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    frequency: str
    bars: tuple[MarketBar, ...]
    quality: QualityDecision
    dq_request: DQTriggerRequest | None
    error_message: str | None = None
    error_kind: ErrorKind | None = Field(default=None, exclude=True)


class MarketFactBatch(BaseModel):
    """Read-only, source-stamped research facts for an instrument."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: Literal["PandaData"] = "PandaData"
    fact_kind: Literal["company_disclosure", "margin_balance"]
    symbol: str
    requested_at: datetime
    facts: tuple[NormalizedFact, ...]
    trade_eligible: Literal[False] = False


class QuoteExecution(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    batch: QuoteBatch
    dq_requests: tuple[DQTriggerRequest, ...]


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
        bar_cache: PersistentBarCache | None = None,
    ) -> None:
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
        self._clock = clock
        self._readiness_cache: tuple[float, tuple[bool, str]] | None = None
        self._bar_cache = bar_cache
        self._published_state = published_state or FailClosedPublishedState()
        self._quality_gate = quality_gate or QualityGate(
            InMemoryScopeFreezeRepository()
        )
        self._latest_quality: dict[str, QualityDecision] = {}

    @classmethod
    def from_environment(
        cls,
    ) -> MarketDataService:
        adapter = PandaDataAdapter.from_environment()
        cache_path = Path(
            os.getenv(
                "FINANCE_GOD_MARKET_BAR_CACHE_PATH",
                str(Path.cwd() / "data" / "market-bars.sqlite3"),
            )
        )
        return cls(
            adapter=adapter,
            bar_cache=PersistentBarCache(cache_path),
            published_state=PandaCalendarPublishedState(adapter),
        )

    @property
    def instrument_master(self) -> InstrumentMaster:
        return self._master

    def resolve(self, symbol: str) -> InstrumentId:
        return self._master.resolve(symbol)

    def _fetch_snapshot(
        self, instrument: InstrumentId
    ) -> DataEnvelope[NormalizedSnapshot]:
        observed_at = self._aware_now()
        trading_date = observed_at.astimezone(_market_zone(instrument.market)).strftime(
            "%Y%m%d"
        )
        publication = self._published_state.latest_released(
            instrument=instrument,
            category=DataCategory.BAR,
            frequency=DataFrequency.MINUTE_1,
            trading_date=trading_date,
            observed_at=observed_at,
        )
        envelope = self._adapter.fetch_snapshot(
            instrument,
            release_state=publication.state,
            expected_date=publication.trading_date,
            provider_published_at=publication.provider_published_at,
        )
        return envelope

    def read_bars(
        self,
        symbol: str,
        *,
        limit: int = 80,
        frequency_override: DataFrequency | None = None,
    ) -> MarketBarsResult:
        """Read a bounded normalized bar window, using a persistent local cache."""

        instrument = self.resolve(symbol)
        now = self._aware_now()
        market_today = now.astimezone(_market_zone(instrument.market))
        if frequency_override is not None:
            frequency = frequency_override
        elif (
            instrument.market is MarketType.CN
            and instrument.asset_class.value == "equity"
        ):
            frequency = DataFrequency.MINUTE_1
        else:
            frequency = DataFrequency.DAILY
        cache_key = f"{frequency.value}:{limit}"
        cached = (
            self._bar_cache.get(instrument.symbol, cache_key)
            if self._bar_cache is not None
            else None
        )
        cache_ttl = 5.0 if frequency is DataFrequency.MINUTE_1 else 3_600.0
        if cached is not None and time() - cached[0] < cache_ttl:
            return MarketBarsResult.model_validate(cached[1])

        if frequency is DataFrequency.MINUTE_1:
            start = end = market_today.strftime("%Y%m%d")
        else:
            end = market_today.strftime("%Y%m%d")
            start = (market_today - timedelta(days=limit + 60)).strftime("%Y%m%d")
        publication = self._published_state.latest_released(
            instrument=instrument,
            category=DataCategory.BAR,
            frequency=frequency,
            trading_date=end,
            observed_at=now,
        )
        if frequency is DataFrequency.MINUTE_1:
            start = end = publication.trading_date
        else:
            end = publication.trading_date
        envelope = self._adapter.fetch_bars(
            instrument,
            frequency=frequency,
            start_date=start,
            end_date=end,
            limit=limit,
            release_state=publication.state,
            provider_published_at=publication.provider_published_at,
        )
        outcome = self.evaluate_quality(
            envelope,
            f"{instrument.symbol}:{frequency.value}",
            category=DataCategory.BAR,
            frequency=frequency,
        )
        error_message = (
            (
                envelope.diagnostics[-1].message
                if envelope.diagnostics
                else "PandaData returned no normalized bars"
            )
            if not envelope.items
            else None
        )
        live_result = MarketBarsResult(
            frequency=_display_frequency(frequency),
            bars=tuple(_bar(item) for item in envelope.items),
            quality=outcome.decision,
            dq_request=outcome.dq_request,
            error_message=error_message,
            error_kind=_envelope_error_kind(envelope) if not envelope.items else None,
        )
        if not live_result.bars:
            return live_result
        cached_bars = (
            MarketBarsResult.model_validate(cached[1]).bars
            if cached is not None
            else ()
        )
        merged_by_time = {item.time: item for item in cached_bars}
        merged_by_time.update({item.time: item for item in live_result.bars})
        merged_result = live_result.model_copy(
            update={
                "bars": tuple(
                    merged_by_time[key]
                    for key in sorted(merged_by_time, reverse=True)
                )
            }
        )
        if self._bar_cache is not None:
            self._bar_cache.put(
                instrument.symbol,
                cache_key,
                merged_result.model_dump(mode="json"),
            )
        return merged_result

    def read_historical_daily_bars(
        self,
        symbol: str,
        *,
        start_date: str,
        end_date: str,
        limit: int = 1_000,
    ) -> MarketBarsResult:
        """Read a caller-bounded released daily series for research evidence."""

        instrument = self.resolve(symbol)
        envelope = self._adapter.fetch_bars(
            instrument,
            frequency=DataFrequency.DAILY,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            release_state=ReleaseState.RELEASED,
        )
        outcome = self.evaluate_quality(
            envelope,
            f"{instrument.symbol}:{DataFrequency.DAILY.value}",
            category=DataCategory.BAR,
            frequency=DataFrequency.DAILY,
        )
        error_message = (
            (
                envelope.diagnostics[-1].message
                if envelope.diagnostics
                else "PandaData returned no normalized daily bars"
            )
            if not envelope.items
            else None
        )
        return MarketBarsResult(
            frequency=_display_frequency(DataFrequency.DAILY),
            bars=tuple(_bar(item) for item in envelope.items),
            quality=outcome.decision,
            dq_request=outcome.dq_request,
            error_message=error_message,
            error_kind=_envelope_error_kind(envelope) if not envelope.items else None,
        )

    def read_historical_minute_bars(
        self,
        symbol: str,
        *,
        trading_date: str,
        limit: int = 1_000,
    ) -> MarketBarsResult:
        """Read released A-share one-minute bars for one historical trading day."""

        instrument = self.resolve(symbol)
        envelope = self._adapter.fetch_bars(
            instrument,
            frequency=DataFrequency.MINUTE_1,
            start_date=trading_date,
            end_date=trading_date,
            limit=limit,
            release_state=ReleaseState.RELEASED,
        )
        outcome = self.evaluate_quality(
            envelope,
            f"{instrument.symbol}:{DataFrequency.MINUTE_1.value}",
            category=DataCategory.BAR,
            frequency=DataFrequency.MINUTE_1,
        )
        error_message = (
            envelope.diagnostics[-1].message
            if envelope.diagnostics and not envelope.items
            else ("PandaData returned no historical minute bars" if not envelope.items else None)
        )
        return MarketBarsResult(
            frequency=_display_frequency(DataFrequency.MINUTE_1),
            bars=tuple(_bar(item) for item in envelope.items),
            quality=outcome.decision,
            dq_request=outcome.dq_request,
            error_message=error_message,
            error_kind=_envelope_error_kind(envelope) if not envelope.items else None,
        )

    def read_information_facts(
        self,
        symbol: str,
        *,
        start_quarter: str,
        end_quarter: str,
        limit: int = 20,
    ) -> MarketFactBatch:
        """Return source-stamped financial-report disclosures, never summaries."""
        _validate_fact_limit(limit)
        instrument = self.resolve(symbol)
        if (
            instrument.market is not MarketType.CN
            or instrument.asset_class.value != "equity"
        ):
            raise MarketDataError(
                ErrorKind.CAPABILITY,
                "company disclosure facts require a CN equity instrument",
                endpoint="get_fina_reports",
            )
        envelope = self._adapter.fetch_financial_report_facts(
            instrument,
            start_quarter=start_quarter,
            end_quarter=end_quarter,
        )
        return _fact_batch(
            envelope=envelope,
            fact_kind="company_disclosure",
            symbol=instrument.symbol,
            requested_at=self._aware_now(),
            limit=limit,
        )

    def read_sentiment_facts(
        self,
        symbol: str,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 60,
    ) -> MarketFactBatch:
        """Return raw margin-balance observations; no inferred sentiment score."""
        _validate_fact_limit(limit)
        if (start_date is None) != (end_date is None):
            raise ValueError("start_date and end_date must be supplied together")
        now = self._aware_now()
        if start_date is None:
            end_date = now.strftime("%Y%m%d")
            start_date = (now - timedelta(days=30)).strftime("%Y%m%d")
        instrument = self.resolve(symbol)
        if (
            instrument.market is not MarketType.CN
            or instrument.asset_class.value != "equity"
        ):
            raise MarketDataError(
                ErrorKind.CAPABILITY,
                "margin-balance sentiment facts require a CN equity instrument",
                endpoint="get_margin",
            )
        envelope = self._adapter.fetch_monitor_facts(
            dataset=MonitorDataset.MARGIN,
            symbols=(instrument.provider_symbol,),
            start_date=start_date,
            end_date=end_date,
        )
        return _fact_batch(
            envelope=envelope,
            fact_kind="margin_balance",
            symbol=instrument.symbol,
            requested_at=now,
            limit=limit,
        )

    def catalog(self) -> tuple[dict[str, object], ...]:
        return self._adapter.catalog()

    def probe_readiness(self) -> tuple[bool, str]:
        clock_value = self._clock()
        cached = self._readiness_cache
        if cached is not None and clock_value - cached[0] < _READINESS_CACHE_SECONDS:
            return cached[1]
        try:
            observed_at = self._aware_now()
            self._published_state.probe(observed_at)
            self._probe_page_dependencies()
        except MarketDataError as error:
            result = False, error.public_code.value
        else:
            result = True, "ready"
        self._readiness_cache = (clock_value, result)
        return result

    def _probe_page_dependencies(self) -> None:
        # Use the same publication-aware snapshot path as live quotes so the
        # canary resolves the latest released session on weekends/holidays
        # instead of querying an empty same-day realtime endpoint.
        instrument = self.resolve(_READINESS_CANARY_SYMBOL)
        quote = self._fetch_snapshot(instrument)
        if quote.diagnostics or len(quote.items) != 1:
            raise MarketDataResponseError(
                "quote readiness canary did not return one normalized item",
                endpoint=_single_source_endpoint(quote),
            )
        trading_date = quote.items[0].source.trading_date
        observed_at = self._aware_now()
        publication = self._published_state.latest_released(
            instrument=instrument,
            category=DataCategory.BAR,
            frequency=DataFrequency.MINUTE_1,
            trading_date=trading_date,
            observed_at=observed_at,
        )
        bars = self._adapter.fetch_bars(
            instrument,
            frequency=DataFrequency.MINUTE_1,
            start_date=publication.trading_date,
            end_date=publication.trading_date,
            limit=1,
            release_state=publication.state,
            provider_published_at=publication.provider_published_at,
        )
        if bars.diagnostics or not bars.items:
            raise MarketDataResponseError(
                "bar readiness canary did not return a normalized item",
                endpoint=_single_source_endpoint(bars),
            )

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

    def evaluate_quality(
        self,
        envelope: DataEnvelope[Any],
        affected_scope: str,
        *,
        category: DataCategory,
        frequency: DataFrequency,
    ) -> QualityOutcome:
        endpoint = _single_source_endpoint(envelope)
        decision = self._quality_gate.evaluate(
            envelope,
            context=QualityContext(
                affected_scope=affected_scope,
                category=category,
                frequency=frequency,
                instrument_master_identity=self._master.identity,
                instrument_master_version=self._master.version,
                source_endpoint=endpoint,
            ),
            observed_at=self._aware_now(),
        )
        self._latest_quality[affected_scope] = decision
        return QualityOutcome(
            decision=decision,
            dq_request=build_dq_trigger_request(
                decision,
                source_workflow="market_data",
            ),
        )

    def _aware_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            raise ValueError("service clock must return timezone-aware datetime")
        return value.astimezone(_UTC)


class _QuoteCoordinator:
    """Internal shared polling coordinator used only by the async application."""

    def __init__(
        self,
        service: MarketDataService,
        *,
        refresh_after_seconds: float = 0.9,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._service = service
        self._coordinator = SnapshotCoordinator(
            service._fetch_snapshot,
            refresh_after_seconds=refresh_after_seconds,
            clock=clock,
        )
        self._seen: set[str] = set()

    async def get(self, symbols: Iterable[str]) -> QuoteExecution:
        requested = _bounded_symbols(symbols)
        instruments: list[InstrumentId] = []
        resolution_errors: dict[str, str] = {}
        for symbol in requested:
            try:
                instruments.append(self._service.resolve(symbol))
            except UnknownInstrumentError as error:
                resolution_errors[symbol] = str(error)
        cache_hit = not resolution_errors and all(
            item.symbol in self._seen for item in instruments
        )
        if instruments:
            result = await self._coordinator.get(instruments)
            result_items = result.items
            diagnostics = result.diagnostics
        else:
            result_items = ()
            diagnostics = ()
        successful = {item.instrument.symbol for item in result_items}
        self._seen.update(successful)
        errors = resolution_errors | {
            item.scope.split(":", maxsplit=1)[0]: item.message for item in diagnostics
        }
        quality: dict[str, QualityDecision] = {}
        dq_requests: list[DQTriggerRequest] = []
        for instrument in instruments:
            instrument_items = tuple(
                item
                for item in result_items
                if item.instrument.symbol == instrument.symbol
            )
            instrument_diagnostics = tuple(
                item
                for item in diagnostics
                if item.scope.split(":", maxsplit=1)[0] == instrument.symbol
            )
            empty_meaning = (
                EmptyMeaning.NOT_EMPTY
                if instrument_items
                else EmptyMeaning.UNEXPECTED_MISSING
            )
            envelope = DataEnvelope(
                instrument_items,
                instrument_diagnostics,
                empty_meaning,
            )
            frequency = (
                instrument_items[0].source.frequency
                if instrument_items
                else DataFrequency.SNAPSHOT
            )
            outcome = self._service.evaluate_quality(
                envelope,
                instrument.symbol,
                category=DataCategory.SNAPSHOT,
                frequency=frequency,
            )
            quality[instrument.symbol] = outcome.decision
            if outcome.dq_request is not None:
                dq_requests.append(outcome.dq_request)
        batch = QuoteBatch(
            requested_at=datetime.now(_UTC),
            cache_hit=cache_hit,
            quotes=tuple(_quote(item) for item in result_items),
            errors=errors,
            diagnostics=diagnostics,
            quality=quality,
        )
        return QuoteExecution(batch=batch, dq_requests=tuple(dq_requests))


class MarketDataApplication:
    """Async read boundary for market data.

    Public GET requests return diagnostics but never create durable workflows.
    Data-quality automation belongs to an explicit background/outbox path so a
    browser refresh cannot mutate workflow state or overload the Worker.
    """

    def __init__(
        self,
        service: MarketDataService,
        *,
        dq_workflow: DQWorkflowPort | None = None,
    ) -> None:
        self._service = service
        self._quotes = _QuoteCoordinator(service)
        # Kept in the constructor for compatibility with existing composition
        # code; public reads deliberately do not call the command port.
        del dq_workflow

    def probe_readiness(self) -> tuple[bool, str]:
        return self._service.probe_readiness()

    async def quotes(self, symbols: Iterable[str]) -> QuoteBatch:
        execution = await self._quotes.get(symbols)
        return execution.batch

    async def bars(self, symbol: str, *, limit: int = 80) -> MarketBarsResult:
        result = await asyncio.to_thread(
            self._service.read_bars,
            symbol,
            limit=limit,
        )
        if not result.bars:
            raise MarketDataError(
                result.error_kind or ErrorKind.SCHEMA,
                result.error_message or "PandaData returned no normalized bars",
            )
        return result

    async def historical_daily_bars(
        self,
        symbol: str,
        *,
        start_date: str,
        end_date: str,
        limit: int = 1_000,
    ) -> MarketBarsResult:
        result = await asyncio.to_thread(
            self._service.read_historical_daily_bars,
            symbol,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
        )
        if not result.bars:
            raise MarketDataError(
                result.error_kind or ErrorKind.SCHEMA,
                result.error_message
                or "PandaData returned no normalized historical daily bars",
            )
        return result

    async def information_facts(
        self,
        symbol: str,
        *,
        start_quarter: str,
        end_quarter: str,
        limit: int = 20,
    ) -> MarketFactBatch:
        return await asyncio.to_thread(
            self._service.read_information_facts,
            symbol,
            start_quarter=start_quarter,
            end_quarter=end_quarter,
            limit=limit,
        )

    async def sentiment_facts(
        self,
        symbol: str,
        *,
        start_date: str,
        end_date: str,
        limit: int = 60,
    ) -> MarketFactBatch:
        return await asyncio.to_thread(
            self._service.read_sentiment_facts,
            symbol,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
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
        session_alignment=(
            "latest_released_session"
            if item.source.data_time.date()
            < item.source.ingested_at.astimezone(item.source.data_time.tzinfo).date()
            else "current_session"
        ),
        market_status=item.freshness.release_state.value,
        source_endpoint=item.source.endpoint,
        capability_version=item.source.capability_version,
        instrument_master_identity=item.source.instrument_master_identity,
        instrument_master_version=item.source.instrument_master_version,
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
        source_endpoint=item.source.endpoint,
        capability_version=item.source.capability_version,
        instrument_master_identity=item.source.instrument_master_identity,
        instrument_master_version=item.source.instrument_master_version,
    )


def _fact_batch(
    *,
    envelope: DataEnvelope[NormalizedFact],
    fact_kind: Literal["company_disclosure", "margin_balance"],
    symbol: str,
    requested_at: datetime,
    limit: int,
) -> MarketFactBatch:
    if not envelope.items:
        message = (
            envelope.diagnostics[-1].message
            if envelope.diagnostics
            else "PandaData returned no research facts"
        )
        raise MarketDataResponseError(
            message, endpoint=_single_source_endpoint(envelope)
        )
    return MarketFactBatch(
        fact_kind=fact_kind,
        symbol=symbol,
        requested_at=requested_at,
        facts=envelope.items[:limit],
    )


def _validate_fact_limit(limit: int) -> None:
    if isinstance(limit, bool) or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")


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


def _single_source_endpoint(envelope: DataEnvelope[Any]) -> str | None:
    endpoints = {
        endpoint
        for endpoint in (
            *(
                getattr(getattr(item, "source", None), "endpoint", None)
                for item in envelope.items
            ),
            *(issue.endpoint for issue in envelope.diagnostics),
        )
        if endpoint is not None
    }
    if len(endpoints) > 1:
        raise ValueError("quality envelope contains conflicting source endpoints")
    return next(iter(endpoints), None)


def _envelope_error_kind(envelope: DataEnvelope[Any]) -> ErrorKind:
    if not envelope.diagnostics:
        return ErrorKind.SCHEMA
    return {
        DiagnosticCode.CAPABILITY_DISABLED: ErrorKind.CAPABILITY,
        DiagnosticCode.UNSUPPORTED_CATEGORY: ErrorKind.CAPABILITY,
        DiagnosticCode.INVALID_PARAMETER: ErrorKind.PARAMETER,
        DiagnosticCode.AUTHENTICATION_FAILED: ErrorKind.AUTHENTICATION,
        DiagnosticCode.PERMISSION_DENIED: ErrorKind.PERMISSION,
        DiagnosticCode.TRANSIENT_UPSTREAM: ErrorKind.TRANSIENT,
        DiagnosticCode.UNEXPECTED_MISSING: ErrorKind.EMPTY,
    }.get(envelope.diagnostics[-1].code, ErrorKind.SCHEMA)
