"""Scope-authorized PandaData adapter and strict endpoint routing."""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from importlib import import_module, metadata
from itertools import pairwise
from threading import Event, Lock, Thread
from time import monotonic
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from .capabilities import (
    CAPABILITY_CATALOG_VERSION,
    CATALOG,
    CapabilityDisabledError,
    PandaDataCapabilityCatalog,
    request_shape,
)
from .contracts import (
    AssetClass,
    DataCategory,
    DataEnvelope,
    DataFrequency,
    DiagnosticCode,
    EmptyMeaning,
    FactField,
    Freshness,
    InstrumentId,
    MarketType,
    MonitorDataset,
    NormalizedBar,
    NormalizedCalendarDay,
    NormalizedFact,
    NormalizedIndexWeight,
    NormalizedMasterRecord,
    NormalizedSnapshot,
    ReleaseState,
    SourceStamp,
)
from .errors import (
    ErrorKind,
    MarketDataConfigurationError,
    MarketDataError,
    MarketDataResponseError,
    classify_upstream_error,
    redact_text,
)
from .freshness import DEFAULT_FRESHNESS_POLICY, FreshnessPolicy
from .instruments import DEFAULT_INSTRUMENT_MASTER, InstrumentMaster
from .normalization import PandaDataNormalizer, diagnostic, records_from_frame
from .transport import (
    OperationBudget,
    PandaData012TransportPolicy,
    PandaTransportPolicy,
)

_UTC = ZoneInfo("UTC")
_DATE_PATTERN = re.compile(r"^\d{8}$")
_MAX_SYMBOLS = 40
_MAX_LIMIT = 1_000
_MAX_DATE_SPAN_DAYS = 3_660
_MAX_FACT_FIELDS = 40
_DEFAULT_OPERATION_BUDGET = OperationBudget()


@dataclass(frozen=True)
class PandaCredentials:
    username: str = field(repr=False)
    password: str = field(repr=False)
    base_url: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.username or not self.password:
            raise MarketDataConfigurationError(
                "PANDA_DATA_USERNAME and PANDA_DATA_PASSWORD are required"
            )

    @classmethod
    def from_environment(cls) -> PandaCredentials:
        return cls(
            username=os.environ.get("PANDA_DATA_USERNAME", ""),
            password=os.environ.get("PANDA_DATA_PASSWORD", ""),
            base_url=os.environ.get("PANDA_DATA_BASE_URL") or None,
        )

    @property
    def secrets(self) -> tuple[str, ...]:
        return tuple(
            value for value in (self.username, self.password, self.base_url) if value
        )


class FactorQuery(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    instrument_symbol: str = Field(
        min_length=1,
        max_length=32,
        pattern=r"^[A-Z0-9._-]+$",
    )
    instrument_master_identity: str = Field(min_length=1, max_length=96)
    instrument_master_version: str = Field(min_length=64, max_length=64)
    start_date: str = Field(pattern=r"^\d{8}$")
    end_date: str = Field(pattern=r"^\d{8}$")
    factors: tuple[str, ...] = Field(min_length=1, max_length=40)

    @classmethod
    def from_master(
        cls,
        master: InstrumentMaster,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
        factors: tuple[str, ...],
    ) -> FactorQuery:
        instrument = master.resolve(symbol)
        return cls(
            instrument_symbol=instrument.symbol,
            instrument_master_identity=master.identity,
            instrument_master_version=master.version,
            start_date=start_date,
            end_date=end_date,
            factors=factors,
        )


class UnsupportedDataCategoryError(MarketDataError):
    def __init__(self, message: str) -> None:
        super().__init__(ErrorKind.CAPABILITY, message)


class PandaDataAdapter:
    """DI adapter; every call is authorized against an exact verified scope."""

    def __init__(
        self,
        *,
        sdk: Any,
        sdk_version: str,
        credentials: PandaCredentials,
        transport_policy: PandaTransportPolicy,
        instrument_master: InstrumentMaster = DEFAULT_INSTRUMENT_MASTER,
        catalog: PandaDataCapabilityCatalog = CATALOG,
        freshness_policy: FreshnessPolicy = DEFAULT_FRESHNESS_POLICY,
        now: Callable[[], datetime] | None = None,
        operation_clock: Callable[[], float] = monotonic,
        operation_budget: OperationBudget = _DEFAULT_OPERATION_BUDGET,
    ) -> None:
        catalog.validate_sdk(sdk, sdk_version=sdk_version)
        self._sdk = sdk
        self._credentials = credentials
        self._catalog = catalog
        self._freshness_policy = freshness_policy
        self._transport_policy = transport_policy
        self._instrument_master = instrument_master
        self._operation_clock = operation_clock
        self._operation_budget = operation_budget
        self._normalizer = PandaDataNormalizer(
            freshness_policy,
            instrument_master_identity=instrument_master.identity,
            instrument_master_version=instrument_master.version,
        )
        self._now = now or (lambda: datetime.now(_UTC))
        self._auth_lock = Lock()
        self._auth_transport_configured = False
        self._authenticated = False
        self._deadline_failed = False

    @classmethod
    def from_environment(cls) -> PandaDataAdapter:
        try:
            sdk = import_module("panda_data")
            sdk_version = metadata.version("panda_data")
        except (ModuleNotFoundError, metadata.PackageNotFoundError) as error:
            raise MarketDataConfigurationError(
                "audited panda_data 0.0.12 is not installed"
            ) from error
        return cls(
            sdk=sdk,
            sdk_version=sdk_version,
            credentials=PandaCredentials.from_environment(),
            transport_policy=PandaData012TransportPolicy(),
        )

    def fetch_snapshot(
        self,
        instrument: InstrumentId,
        *,
        release_state: ReleaseState,
        expected_date: str | None = None,
        provider_published_at: datetime | None = None,
    ) -> DataEnvelope[NormalizedSnapshot]:
        instrument = self._canonical_instrument(instrument)
        if instrument.asset_class in {
            AssetClass.ETF,
            AssetClass.LOF,
            AssetClass.FUND,
        }:
            return self._disabled(
                instrument.symbol,
                "fund/ETF/LOF capability is disabled; no stock or deprecated-fund fallback",
                "get_fund_daily",
            )
        if instrument.asset_class is not AssetClass.EQUITY:
            return self._disabled(
                instrument.symbol,
                "asset class has no verified snapshot endpoint",
                None,
            )
        if instrument.market is not MarketType.CN:
            return self._disabled(
                instrument.symbol,
                "HK/US verified capability is closed-session daily data, not snapshot",
                None,
            )
        endpoint = "get_stock_rt_min"
        if release_state is not ReleaseState.RELEASED:
            return self._not_released(
                instrument.symbol,
                endpoint,
                release_state,
            )
        frame = self._request(
            endpoint,
            {"A_SHARE_STOCK", "frequency=1m"},
            symbol=instrument.provider_symbol,
            frequency="1m",
        )
        records = records_from_frame(frame, endpoint=endpoint)
        trading_date = (
            _validate_date(expected_date)
            if expected_date
            else _reported_trading_date(records)
            or self._utc_now()
            .astimezone(ZoneInfo("Asia/Shanghai"))
            .strftime("%Y%m%d")
        )
        bars = self._normalizer.bars(
            records,
            instrument=instrument,
            endpoint=endpoint,
            frequency=DataFrequency.MINUTE_1,
            ingested_at=self._utc_now(),
            release_state=release_state,
            start_date=trading_date,
            end_date=trading_date,
            limit=1,
            provider_published_at=provider_published_at,
        )
        if not bars.items:
            quote_diagnostics = tuple(
                diagnostic(
                    code=item.code,
                    scope=instrument.symbol,
                    message=item.message,
                    endpoint=item.endpoint,
                    severity=item.severity,
                    empty_meaning=item.empty_meaning,
                    retryable=item.retryable,
                    details=dict(item.details),
                )
                for item in bars.diagnostics
            )
            return DataEnvelope((), quote_diagnostics, bars.empty_meaning)
        latest = bars.items[0]
        return DataEnvelope(
            (
                NormalizedSnapshot(
                    instrument=latest.instrument,
                    source=latest.source,
                    freshness=latest.freshness,
                    last=latest.close,
                    open=latest.open,
                    high=latest.high,
                    low=latest.low,
                    previous_close=None,
                    volume=latest.volume,
                    amount=latest.amount,
                ),
            ),
            (),
            EmptyMeaning.NOT_EMPTY,
        )

    def fetch_bars(
        self,
        instrument: InstrumentId,
        *,
        frequency: DataFrequency,
        start_date: str,
        end_date: str,
        limit: int,
        release_state: ReleaseState,
        provider_published_at: datetime | None = None,
    ) -> DataEnvelope[NormalizedBar]:
        instrument = self._canonical_instrument(instrument)
        start, end = _bounded_date_range(start_date, end_date)
        bounded_limit = _validate_limit(limit)
        if instrument.asset_class in {
            AssetClass.ETF,
            AssetClass.LOF,
            AssetClass.FUND,
        }:
            return self._disabled(
                f"{instrument.symbol}:{frequency.value}",
                "fund/ETF/LOF capability is disabled; no stock or deprecated-fund fallback",
                "get_fund_daily",
            )
        market_today = (
            self._utc_now()
            .astimezone(
                {
                    MarketType.CN: ZoneInfo("Asia/Shanghai"),
                    MarketType.HK: ZoneInfo("Asia/Hong_Kong"),
                    MarketType.US: ZoneInfo("America/New_York"),
                }[instrument.market]
            )
            .strftime("%Y%m%d")
        )
        if end > market_today:
            raise ValueError("future market data cannot be requested")
        endpoint, scopes, params = self._bar_request(
            instrument,
            frequency,
            start,
            end,
            realtime_minute=end == market_today,
        )
        if release_state is not ReleaseState.RELEASED:
            return self._not_released(
                f"{instrument.symbol}:{frequency.value}",
                endpoint,
                release_state,
            )
        frame = self._request(endpoint, scopes, **params)
        return self._normalizer.bars(
            records_from_frame(frame, endpoint=endpoint),
            instrument=instrument,
            endpoint=endpoint,
            frequency=frequency,
            ingested_at=self._utc_now(),
            release_state=release_state,
            start_date=start,
            end_date=end,
            limit=bounded_limit,
            provider_published_at=provider_published_at,
        )

    def fetch_master(
        self, instruments: Iterable[InstrumentId]
    ) -> DataEnvelope[NormalizedMasterRecord]:
        requested = _bounded_instruments(instruments)
        requested = tuple(self._canonical_instrument(item) for item in requested)
        if any(
            item.asset_class in {AssetClass.ETF, AssetClass.LOF, AssetClass.FUND}
            for item in requested
        ):
            return self._disabled(
                "instrument-master",
                "fund/ETF/LOF master capability is disabled",
                "get_fund_detail",
            )
        groups: dict[tuple[str, frozenset[str]], list[InstrumentId]] = {}
        for item in requested:
            endpoint, scopes = _master_endpoint(item)
            groups.setdefault((endpoint, scopes), []).append(item)
        result: list[NormalizedMasterRecord] = []
        for (endpoint, scopes), group in groups.items():
            frame = self._request(
                endpoint,
                scopes,
                symbol=[item.provider_symbol for item in group],
            )
            records = records_from_frame(frame, endpoint=endpoint)
            if not records:
                return self._unexpected_missing("instrument-master", endpoint)
            returned_symbols = [
                str(record.get("symbol", "")).upper() for record in records
            ]
            expected_symbols = {item.provider_symbol for item in group}
            if (
                len(returned_symbols) != len(set(returned_symbols))
                or set(returned_symbols) != expected_symbols
            ):
                return self._schema_drift(
                    "instrument-master",
                    endpoint,
                    "master response has duplicate, missing, or unexpected symbols",
                )
            by_symbol = {
                str(record.get("symbol", "")).upper(): record for record in records
            }
            ingested_at = self._utc_now()
            for item in group:
                record = by_symbol.get(item.provider_symbol)
                name = record.get("name") if record else None
                if not isinstance(name, str) or not name.strip():
                    return self._schema_drift(
                        item.symbol, endpoint, "master record is missing symbol/name"
                    )
                evidence = self._reference_evidence(
                    endpoint=endpoint,
                    data_time=ingested_at,
                    ingested_at=ingested_at,
                    frequency=DataFrequency.STATIC,
                    market=item.market,
                    category=DataCategory.MASTER,
                    release_state=ReleaseState.UNKNOWN,
                )
                result.append(
                    NormalizedMasterRecord(
                        instrument=item,
                        name=name.strip(),
                        source=evidence[0],
                        freshness=evidence[1],
                    )
                )
        return DataEnvelope(tuple(result), (), EmptyMeaning.NOT_EMPTY)

    def fetch_calendar(
        self,
        *,
        market: MarketType,
        start_date: str,
        end_date: str,
    ) -> DataEnvelope[NormalizedCalendarDay]:
        start, end = _bounded_date_range(start_date, end_date)
        exchange = {
            MarketType.CN: "SH",
            MarketType.HK: "HK",
            MarketType.US: "US",
        }[market]
        endpoint = "get_trade_cal"
        frame = self._request(
            endpoint,
            {exchange},
            start_date=start,
            end_date=end,
            exchange=exchange,
        )
        records = records_from_frame(frame, endpoint=endpoint)
        if not records:
            return self._unexpected_missing(f"calendar:{exchange}", endpoint)
        ingested_at = self._utc_now()
        items: list[NormalizedCalendarDay] = []
        for record in records:
            trade_date = record.get(
                "trade_date",
                record.get("date", record.get("nature_date")),
            )
            is_open = record.get(
                "is_trading_day",
                record.get(
                    "is_open",
                    record.get("trade_status", record.get("is_trade")),
                ),
            )
            try:
                normalized_date = _validate_date(str(trade_date).replace("-", ""))
                normalized_open = _parse_open_flag(is_open)
            except ValueError:
                return self._schema_drift(
                    f"calendar:{exchange}",
                    endpoint,
                    "calendar row is missing date/open-state",
                )
            data_time = datetime.strptime(normalized_date, "%Y%m%d").replace(
                tzinfo=ZoneInfo("UTC")
            )
            evidence = self._reference_evidence(
                endpoint=endpoint,
                data_time=data_time,
                ingested_at=ingested_at,
                frequency=DataFrequency.DAILY,
                market=market,
                category=DataCategory.CALENDAR,
                release_state=ReleaseState.UNKNOWN,
            )
            items.append(
                NormalizedCalendarDay(
                    market=market,
                    trade_date=normalized_date,
                    is_open=normalized_open,
                    source=evidence[0],
                    freshness=evidence[1],
                )
            )
        dates = [item.trade_date for item in items]
        if any(not start <= item <= end for item in dates):
            return self._schema_drift(
                f"calendar:{exchange}",
                endpoint,
                "calendar date is outside request range",
            )
        if any(current <= previous for previous, current in pairwise(dates)):
            return self._schema_drift(
                f"calendar:{exchange}",
                endpoint,
                "calendar contains duplicate or out-of-order dates",
            )
        return DataEnvelope(tuple(items), (), EmptyMeaning.NOT_EMPTY)

    def fetch_factors(self, query: FactorQuery) -> DataEnvelope[NormalizedFact]:
        self._validate_query_master(
            query.instrument_master_identity,
            query.instrument_master_version,
        )
        instrument = self._instrument_master.resolve(query.instrument_symbol)
        if (
            instrument.market is not MarketType.CN
            or instrument.asset_class is not AssetClass.EQUITY
        ):
            return self._disabled(
                f"{instrument.symbol}:factor",
                "factor capability is restricted to authoritative CN equity instruments",
                "get_factor",
            )
        start, end = _bounded_date_range(query.start_date, query.end_date)
        if any(
            not factor
            or len(factor) > 64
            or not re.fullmatch(r"[A-Za-z0-9_.-]+", factor)
            for factor in query.factors
        ):
            raise ValueError("factor names must be bounded identifiers")
        endpoint = "get_factor"
        frame = self._request(
            endpoint,
            {"CN_EQUITY"},
            symbol=instrument.provider_symbol,
            start_date=start,
            end_date=end,
            type="stock",
            factors=list(query.factors),
            index_component="",
        )
        records = records_from_frame(frame, endpoint=endpoint)
        if not records:
            return self._unexpected_missing(f"{instrument.symbol}:factor", endpoint)
        scope = f"{instrument.symbol}:factor"
        ingested_at = self._utc_now()
        items: list[NormalizedFact] = []
        for record in records:
            if str(record.get("symbol", "")).upper() != instrument.provider_symbol:
                return self._schema_drift(
                    scope, endpoint, "factor row symbol conflicts with request"
                )
            raw_time = record.get("date")
            if raw_time is None:
                return self._schema_drift(scope, endpoint, "factor row is missing date")
            try:
                data_time = _parse_fact_time(raw_time)
            except ValueError:
                return self._schema_drift(
                    scope, endpoint, "factor row has invalid date"
                )
            compact = data_time.strftime("%Y%m%d")
            if not start <= compact <= end:
                return self._schema_drift(
                    scope, endpoint, "factor row date is outside request range"
                )
            evidence = self._reference_evidence(
                endpoint=endpoint,
                data_time=data_time,
                ingested_at=ingested_at,
                frequency=DataFrequency.DAILY,
                market=instrument.market,
                category=DataCategory.FACTOR,
                release_state=ReleaseState.UNKNOWN,
            )
            items.append(
                NormalizedFact(
                    category=DataCategory.FACTOR,
                    scope=scope,
                    source=evidence[0],
                    freshness=evidence[1],
                    fields=tuple(
                        FactField(
                            name=str(key),
                            value=_safe_fact_value(value),
                        )
                        for key, value in record.items()
                    ),
                )
            )
        return DataEnvelope(tuple(items), (), EmptyMeaning.NOT_EMPTY)

    def fetch_monitor_facts(
        self,
        *,
        dataset: MonitorDataset,
        symbols: tuple[str, ...],
        start_date: str,
        end_date: str,
        volatility_period: int = 30,
    ) -> DataEnvelope[NormalizedFact]:
        """Fetch one verified monitor dataset as normalized research facts."""
        start, end = _bounded_date_range(start_date, end_date)
        endpoint, scopes, params, required_fields = _monitor_request(
            dataset=dataset,
            symbols=symbols,
            start_date=start,
            end_date=end,
            volatility_period=volatility_period,
        )
        records = _monitor_records(
            self._request(endpoint, scopes, **params), dataset=dataset
        )
        scope = f"agent-monitor:{dataset.value}"
        if not records:
            return self._unexpected_missing(scope, endpoint)
        if any(not required_fields.issubset(record) for record in records):
            return self._schema_drift(
                scope, endpoint, "monitor response is missing required fields"
            )
        ingested_at = self._utc_now()
        facts: list[NormalizedFact] = []
        for record in records:
            try:
                data_time = _parse_fact_time(record.get("date", end))
                source, freshness = self._reference_evidence(
                    endpoint=endpoint,
                    data_time=data_time,
                    ingested_at=ingested_at,
                    frequency=DataFrequency.DAILY,
                    market=MarketType.CN,
                    category=DataCategory.DERIVATIVE_RESEARCH,
                    release_state=ReleaseState.UNKNOWN,
                )
                facts.append(
                    NormalizedFact(
                        category=DataCategory.DERIVATIVE_RESEARCH,
                        scope=scope,
                        source=source,
                        freshness=freshness,
                        fields=tuple(
                            FactField(name=str(key), value=_safe_fact_value(value))
                            for key, value in sorted(record.items())
                        ),
                    )
                )
            except (TypeError, ValueError):
                return self._schema_drift(
                    scope, endpoint, "monitor response contains an invalid fact value"
                )
        return DataEnvelope(tuple(facts), (), EmptyMeaning.NOT_EMPTY)

    def fetch_index_weights(
        self,
        index: InstrumentId,
        *,
        start_date: str,
        end_date: str,
    ) -> DataEnvelope[NormalizedIndexWeight]:
        index = self._canonical_instrument(index)
        if (
            index.market is not MarketType.CN
            or index.asset_class is not AssetClass.INDEX
        ):
            return self._disabled(
                f"{index.symbol}:weights",
                "index weights require an authoritative CN index",
                "get_index_weights",
            )
        _bounded_date_range(start_date, end_date)
        return self._disabled(
            f"{index.symbol}:weights",
            (
                "index weights were verified once but the field-level schema "
                "evidence was not retained; typed normalization is not exposed"
            ),
            "get_index_weights",
        )

    @staticmethod
    def unsupported_research_category(
        category: DataCategory,
    ) -> DataEnvelope[NormalizedFact]:
        issue = diagnostic(
            code=DiagnosticCode.UNSUPPORTED_CATEGORY,
            scope=f"research:{category.value}",
            message=(
                f"{category.value} has no production typed normalizer; "
                "verified-once SDK methods remain research-only and not exposed"
            ),
            endpoint=None,
            empty_meaning=EmptyMeaning.UNEXPECTED_MISSING,
        )
        return DataEnvelope((), (issue,), EmptyMeaning.UNEXPECTED_MISSING)

    def catalog(self) -> tuple[dict[str, object], ...]:
        """Publish the audited catalog, never raw SDK introspection."""
        return tuple(record.model_dump(mode="json") for record in self._catalog.all())

    @property
    def instrument_master(self) -> InstrumentMaster:
        return self._instrument_master

    def _request(self, endpoint: str, scopes: Iterable[str], **params: object) -> Any:
        if self._deadline_failed:
            self._raise_deadline(endpoint)
        deadline = (
            self._operation_clock() + self._operation_budget.operation_deadline_seconds
        )
        try:
            shape = request_shape(
                endpoint,
                scopes,
                parameter_names=params,
                instrument_master_identity=self._instrument_master.identity,
                instrument_master_version=self._instrument_master.version,
            )
            self._catalog.authorize(endpoint, scopes, shape)
        except CapabilityDisabledError as error:
            raise MarketDataError(
                ErrorKind.CAPABILITY, str(error), endpoint=endpoint
            ) from error
        self._authenticate(deadline)
        self._transport_policy.configure_client(
            self._sdk,
            self._operation_budget,
            timeout_seconds=self._remaining_timeout(deadline, endpoint),
        )
        method = getattr(self._sdk, endpoint)
        try:
            return self._run_before_deadline(
                lambda: method(**params),
                deadline=deadline,
                endpoint=endpoint,
            )
        except Exception as error:
            if isinstance(error, MarketDataError):
                raise
            raise classify_upstream_error(
                error, endpoint=endpoint, secrets=self._credentials.secrets
            ) from error

    def _authenticate(self, deadline: float) -> None:
        if self._authenticated:
            return
        with self._auth_lock:
            if self._authenticated:
                return
            arguments = {
                "username": self._credentials.username,
                "password": self._credentials.password,
            }
            if self._credentials.base_url:
                arguments["base_url"] = self._credentials.base_url
            try:
                if not self._auth_transport_configured:
                    self._transport_policy.configure_auth(
                        self._sdk,
                        self._operation_budget,
                        timeout_seconds=self._remaining_timeout(deadline, "init_token"),
                    )
                    self._auth_transport_configured = True
                self._run_before_deadline(
                    lambda: self._sdk.init_token(**arguments),
                    deadline=deadline,
                    endpoint="init_token",
                )
            except MarketDataError:
                raise
            except Exception as error:
                raise classify_upstream_error(
                    error,
                    endpoint="init_token",
                    secrets=self._credentials.secrets,
                ) from error
            self._authenticated = True

    def _remaining_timeout(
        self,
        deadline: float,
        endpoint: str,
    ) -> float:
        remaining = deadline - self._operation_clock()
        if remaining <= 0:
            self._raise_deadline(endpoint)
        return min(remaining, self._operation_budget.request_timeout_seconds)

    def _run_before_deadline(
        self,
        operation: Callable[[], Any],
        *,
        deadline: float,
        endpoint: str,
    ) -> Any:
        timeout = self._remaining_timeout(deadline, endpoint)
        completed = Event()
        values: list[Any] = []
        errors: list[BaseException] = []

        def invoke() -> None:
            try:
                values.append(operation())
            except BaseException as error:  # noqa: BLE001 - re-raised on caller
                errors.append(error)
            finally:
                completed.set()

        Thread(
            target=invoke,
            name=f"pandadata-{endpoint}",
            daemon=True,
        ).start()
        if not completed.wait(timeout):
            self._raise_deadline(endpoint)
        self._remaining_timeout(deadline, endpoint)
        if errors:
            raise errors[0]
        return values[0]

    def _raise_deadline(self, endpoint: str) -> None:
        self._deadline_failed = True
        raise MarketDataError(
            ErrorKind.DEADLINE,
            (
                f"PandaData {endpoint} exceeded "
                f"{self._operation_budget.operation_deadline_seconds}s deadline"
            ),
            endpoint=endpoint,
        )

    @staticmethod
    def _bar_request(
        instrument: InstrumentId,
        frequency: DataFrequency,
        start: str,
        end: str,
        *,
        realtime_minute: bool,
    ) -> tuple[str, frozenset[str], dict[str, object]]:
        if instrument.asset_class is AssetClass.INDEX:
            if (
                instrument.market is not MarketType.CN
                or frequency is not DataFrequency.DAILY
            ):
                raise UnsupportedDataCategoryError(
                    "only CN index daily bars passed capability verification"
                )
            return (
                "get_index_daily",
                frozenset({"CN_INDEX"}),
                {
                    "symbol": instrument.provider_symbol,
                    "start_date": start,
                    "end_date": end,
                },
            )
        if instrument.asset_class is not AssetClass.EQUITY:
            raise UnsupportedDataCategoryError(
                "asset class has no normalized executable price-bar contract"
            )
        if instrument.market is MarketType.CN and frequency is DataFrequency.MINUTE_1:
            if not realtime_minute:
                return (
                    "get_stock_min",
                    frozenset({"A_SHARE_STOCK", "frequency=1m"}),
                    {
                        "symbol": instrument.provider_symbol,
                        "start_date": start,
                        "end_date": end,
                        "frequency": "1m",
                    },
                )
            return (
                "get_stock_rt_min",
                frozenset({"A_SHARE_STOCK", "frequency=1m"}),
                {"symbol": instrument.provider_symbol, "frequency": "1m"},
            )
        if frequency is not DataFrequency.DAILY:
            raise UnsupportedDataCategoryError(
                "requested market/frequency scope was not verified"
            )
        params: dict[str, object] = {
            "symbol": instrument.provider_symbol,
            "start_date": start,
            "end_date": end,
        }
        if instrument.market is MarketType.CN:
            return "get_stock_daily", frozenset({"A_SHARE_STOCK_ONLY"}), params
        if instrument.market is MarketType.HK:
            return "get_hk_daily", frozenset({"HK_EQUITY"}), params
        return (
            "get_us_daily",
            frozenset({"US_EQUITY", "CLOSED_SESSION_ONLY"}),
            params,
        )

    def _reference_evidence(
        self,
        *,
        endpoint: str,
        data_time: datetime,
        ingested_at: datetime,
        frequency: DataFrequency,
        market: MarketType,
        category: DataCategory,
        release_state: ReleaseState,
    ) -> tuple[SourceStamp, Freshness]:
        trading_date = data_time.strftime("%Y%m%d")
        source = SourceStamp(
            endpoint=endpoint,
            instrument_master_identity=self._instrument_master.identity,
            instrument_master_version=self._instrument_master.version,
            data_time=data_time,
            trading_date=trading_date,
            provider_published_at=None,
            ingested_at=ingested_at,
            frequency=frequency,
            capability_version=CAPABILITY_CATALOG_VERSION,
            verification="verified_once_research",
            evidence_ref=(
                "finance_god/market_data/resources/verification-summary-v1.json"
            ),
        )
        freshness = self._freshness_policy.evaluate(
            market=market,
            category=category,
            frequency=frequency,
            data_time=data_time,
            trading_date=trading_date,
            provider_published_at=None,
            evaluated_at=ingested_at,
            release_state=release_state,
        )
        return source, freshness

    def _utc_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            raise ValueError("adapter clock must return timezone-aware datetime")
        return value.astimezone(_UTC)

    def _canonical_instrument(self, instrument: InstrumentId) -> InstrumentId:
        canonical = self._instrument_master.resolve(instrument.symbol)
        if canonical != instrument:
            raise ValueError(
                "instrument does not match authoritative master identity/version"
            )
        return canonical

    def _validate_query_master(
        self,
        identity: str,
        version: str,
    ) -> None:
        if (
            identity != self._instrument_master.identity
            or version != self._instrument_master.version
        ):
            raise ValueError("typed query instrument master identity/version mismatch")

    @staticmethod
    def _disabled(scope: str, message: str, endpoint: str | None) -> DataEnvelope[Any]:
        issue = diagnostic(
            code=DiagnosticCode.CAPABILITY_DISABLED,
            scope=scope,
            message=message,
            endpoint=endpoint,
            empty_meaning=EmptyMeaning.UNEXPECTED_MISSING,
        )
        return DataEnvelope((), (issue,), EmptyMeaning.UNEXPECTED_MISSING)

    @staticmethod
    def _unexpected_missing(scope: str, endpoint: str) -> DataEnvelope[Any]:
        issue = diagnostic(
            code=DiagnosticCode.UNEXPECTED_MISSING,
            scope=scope,
            message="PandaData returned no row for an expected verified query",
            endpoint=endpoint,
            empty_meaning=EmptyMeaning.UNEXPECTED_MISSING,
        )
        return DataEnvelope((), (issue,), EmptyMeaning.UNEXPECTED_MISSING)

    @staticmethod
    def _schema_drift(scope: str, endpoint: str, message: str) -> DataEnvelope[Any]:
        issue = diagnostic(
            code=DiagnosticCode.SCHEMA_DRIFT,
            scope=scope,
            message=message,
            endpoint=endpoint,
            empty_meaning=EmptyMeaning.UNEXPECTED_MISSING,
        )
        return DataEnvelope((), (issue,), EmptyMeaning.UNEXPECTED_MISSING)

    @staticmethod
    def _not_released(
        scope: str,
        endpoint: str,
        release_state: ReleaseState,
    ) -> DataEnvelope[Any]:
        issue = diagnostic(
            code=DiagnosticCode.DATA_NOT_RELEASED,
            scope=scope,
            message=(
                "published-state/calendar policy did not declare this exact "
                f"request released (state={release_state.value}); PandaData was not called"
            ),
            endpoint=endpoint,
            empty_meaning=EmptyMeaning.UNEXPECTED_MISSING,
        )
        return DataEnvelope((), (issue,), EmptyMeaning.UNEXPECTED_MISSING)


def _bounded_instruments(
    instruments: Iterable[InstrumentId],
) -> tuple[InstrumentId, ...]:
    unique = {item.symbol: item for item in instruments}
    if not unique:
        raise ValueError("at least one instrument is required")
    if len(unique) > _MAX_SYMBOLS:
        raise ValueError(f"at most {_MAX_SYMBOLS} instruments are allowed")
    return tuple(unique[symbol] for symbol in sorted(unique))


def _monitor_request(
    *,
    dataset: MonitorDataset,
    symbols: tuple[str, ...],
    start_date: str,
    end_date: str,
    volatility_period: int,
) -> tuple[str, frozenset[str], dict[str, object], frozenset[str]]:
    if dataset is MonitorDataset.MARGIN:
        if len(symbols) != 1:
            raise ValueError("margin monitor data requires exactly one symbol")
        return (
            "get_margin",
            frozenset({"A_SHARE_MARGIN"}),
            {
                "symbol": symbols[0],
                "start_date": start_date,
                "end_date": end_date,
                "margin_type": "stock",
                "fields": ["symbol", "date", "total_balance", "short_balance"],
            },
            frozenset({"date", "total_balance", "short_balance"}),
        )
    if dataset is MonitorDataset.LHB_LIST:
        return (
            "get_lhb_list",
            frozenset({"CN_LHB_LIST"}),
            {
                "symbol": "",
                "type": "",
                "start_date": start_date,
                "end_date": end_date,
                "fields": ["symbol", "date", "amount", "change_rate", "turnover"],
            },
            frozenset({"date", "amount", "change_rate"}),
        )
    if dataset is MonitorDataset.FUTURE_DOMINANT_CORR:
        if len(symbols) < 2:
            raise ValueError("future correlation monitor data requires two symbols")
        return (
            "get_future_dominant_corr",
            frozenset({"FUTURE_DOMINANT_CORR"}),
            {"symbol": list(symbols), "start_date": start_date, "end_date": end_date},
            frozenset({"pair", "correlation"}),
        )
    if dataset is MonitorDataset.OPTION_IMPLIED_VOLATILITY:
        return (
            "get_option_implied_volatility",
            frozenset({"RESEARCH_ONLY"}),
            {
                "symbol": list(symbols),
                "start_date": start_date,
                "end_date": end_date,
                "fields": ["date", "symbol", "implied_volatility"],
            },
            frozenset({"date", "implied_volatility"}),
        )
    if len(symbols) != 1 or volatility_period not in {5, 10, 30, 60, 90, 120, 180, 250, 500}:
        raise ValueError("option volatility monitor data has invalid symbol or period")
    return (
        "get_option_underlying_volatility",
        frozenset({"RESEARCH_ONLY"}),
        {
            "symbol": symbols[0],
            "start_date": start_date,
            "end_date": end_date,
            "exchange": "",
            "period": volatility_period,
            "fields": ["date", "symbol", "close", "historical_volatility", "period"],
        },
        frozenset({"date", "historical_volatility"}),
    )


def _monitor_records(frame: Any, *, dataset: MonitorDataset) -> list[dict[str, Any]]:
    if dataset is not MonitorDataset.FUTURE_DOMINANT_CORR:
        return records_from_frame(frame, endpoint=f"monitor:{dataset.value}")
    if not isinstance(frame, Mapping):
        raise MarketDataResponseError(
            "future correlation monitor response must be a mapping",
            endpoint="get_future_dominant_corr",
        )
    return [
        {"pair": str(pair), "correlation": value}
        for pair, value in sorted(frame.items())
    ]


def _master_endpoint(
    instrument: InstrumentId,
) -> tuple[str, frozenset[str]]:
    if instrument.asset_class is AssetClass.INDEX:
        return "get_index_detail", frozenset({"CN_INDEX"})
    if instrument.asset_class is not AssetClass.EQUITY:
        raise UnsupportedDataCategoryError("asset class master endpoint is not enabled")
    if instrument.market is MarketType.CN:
        return "get_stock_detail", frozenset({"A_SHARE_STOCK_ONLY"})
    if instrument.market is MarketType.HK:
        return "get_hk_detail", frozenset({"HK_EQUITY"})
    return "get_us_detail", frozenset({"US_EQUITY"})


def _validate_date(value: str) -> str:
    if not _DATE_PATTERN.fullmatch(value):
        raise ValueError("date must use YYYYMMDD")
    try:
        date.fromisoformat(f"{value[:4]}-{value[4:6]}-{value[6:]}")
    except ValueError as error:
        raise ValueError("date must be a valid calendar date") from error
    return value


def _reported_trading_date(records: list[dict[str, Any]]) -> str | None:
    if not records:
        return None
    value = records[0].get("datetime") or records[0].get("date")
    compact = "".join(character for character in str(value) if character.isdigit())[:8]
    try:
        return _validate_date(compact)
    except ValueError:
        return None


def _bounded_date_range(start_date: str, end_date: str) -> tuple[str, str]:
    start = _validate_date(start_date)
    end = _validate_date(end_date)
    start_value = date.fromisoformat(f"{start[:4]}-{start[4:6]}-{start[6:]}")
    end_value = date.fromisoformat(f"{end[:4]}-{end[4:6]}-{end[6:]}")
    span = (end_value - start_value).days
    if span < 0:
        raise ValueError("start_date must not be after end_date")
    if span > _MAX_DATE_SPAN_DAYS:
        raise ValueError(f"date range must not exceed {_MAX_DATE_SPAN_DAYS} days")
    return start, end


def _validate_limit(value: int) -> int:
    if isinstance(value, bool) or not 1 <= value <= _MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {_MAX_LIMIT}")
    return value


def _bounded_fact_params(
    params: Mapping[str, str | int | bool | tuple[str, ...]],
) -> dict[str, object]:
    if len(params) > 12:
        raise ValueError("research fact request has too many parameters")
    bounded: dict[str, object] = {}
    for key, value in params.items():
        if isinstance(value, str):
            if not value or len(value) > 64:
                raise ValueError(f"invalid bounded string parameter: {key}")
            bounded[key] = value
        elif isinstance(value, tuple):
            if not value or len(value) > _MAX_FACT_FIELDS:
                raise ValueError(f"invalid bounded list parameter: {key}")
            if any(not item or len(item) > 64 for item in value):
                raise ValueError(f"invalid bounded list item: {key}")
            bounded[key] = list(value)
        elif isinstance(value, (int, bool)):
            bounded[key] = value
        else:
            raise TypeError(f"unsupported parameter type: {key}")
    for key in ("start_date", "end_date", "date"):
        bounded_value = bounded.get(key)
        if isinstance(bounded_value, str):
            bounded[key] = _validate_date(bounded_value)
    if "start_date" in bounded and "end_date" in bounded:
        _bounded_date_range(str(bounded["start_date"]), str(bounded["end_date"]))
    return bounded


def _parse_open_flag(value: object) -> bool:
    if value in (1, "1", True, "Y", "OPEN", "交易"):
        return True
    if value in (0, "0", False, "N", "CLOSED", "休市"):
        return False
    raise ValueError("invalid calendar open flag")


def _parse_fact_time(value: object) -> datetime:
    raw = str(value).strip()
    for format_value in ("%Y%m%d", "%Y-%m-%d", "%Y%m%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, format_value).replace(tzinfo=_UTC)
        except ValueError:
            continue
    raise ValueError("invalid fact time")


def _safe_fact_value(value: object) -> str | int | float | bool | None:
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, str):
            return redact_text(value)
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return redact_text(value)
