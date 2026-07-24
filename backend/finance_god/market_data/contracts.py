"""Immutable normalized market-data contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MarketType(StrEnum):
    CN = "CN"
    HK = "HK"
    US = "US"


class AssetClass(StrEnum):
    EQUITY = "equity"
    ETF = "etf"
    LOF = "lof"
    FUND = "fund"
    INDEX = "index"
    FUTURE = "future"
    OPTION = "option"


class DataCategory(StrEnum):
    SNAPSHOT = "snapshot"
    BAR = "bar"
    CALENDAR = "calendar"
    MASTER = "master"
    FINANCIAL = "financial"
    FACTOR = "factor"
    INDUSTRY = "industry"
    MACRO = "macro"
    DERIVATIVE_RESEARCH = "derivative_research"


class DataFrequency(StrEnum):
    SNAPSHOT = "snapshot"
    MINUTE_1 = "1m"
    DAILY = "1d"
    EVENT = "event"
    STATIC = "static"


class FreshnessStatus(StrEnum):
    CURRENT = "current"
    STALE = "stale"
    NOT_RELEASED = "not_released"
    UNKNOWN = "unknown"


class ReleaseState(StrEnum):
    IN_SESSION = "in_session"
    CLOSED_PENDING = "closed_pending"
    RELEASED = "released"
    UNKNOWN = "unknown"


class DiagnosticSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class DiagnosticCode(StrEnum):
    CAPABILITY_DISABLED = "capability_disabled"
    INVALID_PARAMETER = "invalid_parameter"
    AUTHENTICATION_FAILED = "authentication_failed"
    PERMISSION_DENIED = "permission_denied"
    TRANSIENT_UPSTREAM = "transient_upstream"
    SCHEMA_DRIFT = "schema_drift"
    UNEXPECTED_MISSING = "unexpected_missing"
    VALID_NO_EVENT = "valid_no_event"
    CONFLICT = "conflict"
    REFRESH_FAILED = "refresh_failed"
    DATA_NOT_RELEASED = "data_not_released"
    UNSUPPORTED_CATEGORY = "unsupported_category"
    ENVELOPE_CONTRACT = "envelope_contract"
    UNRESOLVED_QUALITY_FREEZE = "unresolved_quality_freeze"
    UNEXPECTED_INTERNAL = "unexpected_internal"


class EmptyMeaning(StrEnum):
    NOT_EMPTY = "not_empty"
    VALID_NO_EVENT = "valid_no_event"
    UNEXPECTED_MISSING = "unexpected_missing"


class InstrumentId(BaseModel):
    """Canonical instrument identity from the authoritative instrument master."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str = Field(min_length=1, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    provider_symbol: str = Field(
        min_length=1, max_length=32, pattern=r"^[A-Z0-9._-]+$"
    )
    market: MarketType
    asset_class: AssetClass
    currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    aliases: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_aliases(self) -> InstrumentId:
        normalized = tuple(alias.strip().upper() for alias in self.aliases)
        if any(not alias for alias in normalized):
            raise ValueError("instrument aliases cannot be blank")
        if len(normalized) != len(set(normalized)):
            raise ValueError("instrument aliases must be unique")
        expected_currency = {
            MarketType.CN: "CNY",
            MarketType.HK: "HKD",
            MarketType.US: "USD",
        }[self.market]
        if self.currency != expected_currency:
            raise ValueError(
                f"{self.market.value} instruments require {expected_currency}"
            )
        object.__setattr__(self, "aliases", normalized)
        return self


class SourceStamp(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str = Field(default="PandaData", pattern=r"^PandaData$")
    endpoint: str = Field(min_length=5, max_length=96, pattern=r"^get_[a-z0-9_]+$")
    data_time: datetime
    trading_date: str = Field(pattern=r"^\d{8}$")
    provider_published_at: datetime | None = None
    ingested_at: datetime
    frequency: DataFrequency
    capability_version: str = Field(min_length=1, max_length=64)
    verification: str = Field(pattern=r"^verified_once_research$")
    evidence_ref: str = Field(min_length=1, max_length=240)

    @model_validator(mode="after")
    def require_timezone_aware_times(self) -> SourceStamp:
        if self.data_time.tzinfo is None or self.ingested_at.tzinfo is None:
            raise ValueError("source timestamps must be timezone-aware")
        if (
            self.provider_published_at is not None
            and self.provider_published_at.tzinfo is None
        ):
            raise ValueError("provider_published_at must be timezone-aware")
        if self.data_time > self.ingested_at:
            raise ValueError("data_time cannot be later than ingestion")
        if (
            self.provider_published_at is not None
            and (
                self.provider_published_at < self.data_time
                or self.provider_published_at > self.ingested_at
            )
        ):
            raise ValueError(
                "provider publication must be between data and ingestion time"
            )
        return self


class Freshness(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: FreshnessStatus
    evaluated_at: datetime
    data_time: datetime
    trading_date: str = Field(pattern=r"^\d{8}$")
    provider_published_at: datetime | None = None
    threshold_seconds: int = Field(gt=0)
    age_seconds: int = Field(ge=0)
    release_state: ReleaseState
    rule_version: str = Field(min_length=1, max_length=64)
    workflow_key: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=240)

    @model_validator(mode="after")
    def require_timezone_aware_times(self) -> Freshness:
        if self.data_time.tzinfo is None or self.evaluated_at.tzinfo is None:
            raise ValueError("freshness timestamps must be timezone-aware")
        if self.provider_published_at is not None and self.provider_published_at.tzinfo is None:
            raise ValueError("provider publication time must be timezone-aware")
        expected_age = max(
            0,
            int(
                (
                    self.evaluated_at.astimezone(self.data_time.tzinfo)
                    - self.data_time
                ).total_seconds()
            ),
        )
        if self.age_seconds != expected_age:
            raise ValueError("freshness age_seconds is inconsistent with timestamps")
        if self.release_state is ReleaseState.RELEASED:
            if self.provider_published_at is None and self.status is not FreshnessStatus.UNKNOWN:
                raise ValueError(
                    "released data without provider publication must be unknown"
                )
        elif self.release_state in {
            ReleaseState.IN_SESSION,
            ReleaseState.CLOSED_PENDING,
        }:
            if self.status is not FreshnessStatus.NOT_RELEASED:
                raise ValueError("pending release must have not_released freshness")
        elif self.status is not FreshnessStatus.UNKNOWN:
            raise ValueError("unknown release state must have unknown freshness")
        return self


class DataDiagnostic(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: DiagnosticCode
    severity: DiagnosticSeverity
    scope: str = Field(min_length=1, max_length=160)
    message: str = Field(min_length=1, max_length=320)
    fingerprint: str = Field(min_length=16, max_length=64)
    empty_meaning: EmptyMeaning = EmptyMeaning.NOT_EMPTY
    retryable: bool = False
    endpoint: str | None = Field(
        default=None, min_length=5, max_length=96, pattern=r"^get_[a-z0-9_]+$"
    )
    details: tuple[tuple[str, str], ...] = ()


class NormalizedSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    instrument: InstrumentId
    source: SourceStamp
    freshness: Freshness
    last: Decimal = Field(ge=0)
    open: Decimal = Field(ge=0)
    high: Decimal = Field(ge=0)
    low: Decimal = Field(ge=0)
    previous_close: Decimal | None = Field(default=None, ge=0)
    volume: Decimal = Field(ge=0)
    amount: Decimal | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_ohlc(self) -> NormalizedSnapshot:
        _validate_source_freshness(self.source, self.freshness)
        if self.source.frequency is not DataFrequency.SNAPSHOT:
            raise ValueError("snapshot source frequency must be snapshot")
        if self.high < max(self.open, self.last, self.low):
            raise ValueError("high must be greater than or equal to OHLC values")
        if self.low > min(self.open, self.last, self.high):
            raise ValueError("low must be less than or equal to OHLC values")
        return self


class NormalizedBar(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    instrument: InstrumentId
    source: SourceStamp
    freshness: Freshness
    open: Decimal = Field(ge=0)
    high: Decimal = Field(ge=0)
    low: Decimal = Field(ge=0)
    close: Decimal = Field(ge=0)
    volume: Decimal = Field(ge=0)
    amount: Decimal | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_ohlc(self) -> NormalizedBar:
        _validate_source_freshness(self.source, self.freshness)
        if self.source.frequency not in {
            DataFrequency.MINUTE_1,
            DataFrequency.DAILY,
        }:
            raise ValueError("bar source frequency must be 1m or 1d")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high must be greater than or equal to OHLC values")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("low must be less than or equal to OHLC values")
        return self


FactValue = str | int | float | bool | None


class FactField(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=96)
    value: FactValue


class NormalizedFact(BaseModel):
    """Typed research fact; never masquerades as a market snapshot."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    category: DataCategory
    scope: str = Field(min_length=1, max_length=160)
    source: SourceStamp
    freshness: Freshness
    fields: tuple[FactField, ...]

    @model_validator(mode="after")
    def require_research_category(self) -> NormalizedFact:
        _validate_source_freshness(self.source, self.freshness)
        prohibited = {
            DataCategory.SNAPSHOT,
            DataCategory.BAR,
            DataCategory.CALENDAR,
            DataCategory.MASTER,
        }
        if self.category in prohibited:
            raise ValueError("normalized facts cannot use a price/master category")
        return self


class NormalizedMasterRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    instrument: InstrumentId
    name: str = Field(min_length=1, max_length=160)
    source: SourceStamp
    freshness: Freshness

    @model_validator(mode="after")
    def validate_evidence(self) -> NormalizedMasterRecord:
        _validate_source_freshness(self.source, self.freshness)
        if self.source.frequency is not DataFrequency.STATIC:
            raise ValueError("master evidence frequency must be static")
        return self


class NormalizedCalendarDay(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    market: MarketType
    trade_date: str = Field(pattern=r"^\d{8}$")
    is_open: bool
    source: SourceStamp
    freshness: Freshness

    @model_validator(mode="after")
    def validate_evidence(self) -> NormalizedCalendarDay:
        _validate_source_freshness(self.source, self.freshness)
        if self.source.frequency is not DataFrequency.DAILY:
            raise ValueError("calendar evidence frequency must be daily")
        if self.trade_date != self.source.trading_date:
            raise ValueError("calendar trade_date must match source trading_date")
        return self


class NormalizedIndexWeight(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    index: InstrumentId
    constituent_symbol: str = Field(
        min_length=1, max_length=32, pattern=r"^[A-Z0-9._-]+$"
    )
    weight: Decimal = Field(ge=0, le=1)
    source: SourceStamp
    freshness: Freshness

    @model_validator(mode="after")
    def validate_evidence(self) -> NormalizedIndexWeight:
        _validate_source_freshness(self.source, self.freshness)
        return self


T = TypeVar("T")


@dataclass(frozen=True)
class DataEnvelope(Generic[T]):
    items: tuple[T, ...]
    diagnostics: tuple[DataDiagnostic, ...]
    empty_meaning: EmptyMeaning

    def __post_init__(self) -> None:
        if self.items and self.empty_meaning is not EmptyMeaning.NOT_EMPTY:
            raise ValueError("non-empty data cannot carry an empty meaning")
        if not self.items and self.empty_meaning is EmptyMeaning.NOT_EMPTY:
            raise ValueError("empty data requires explicit empty meaning")
        if (
            not self.items
            and self.empty_meaning is EmptyMeaning.UNEXPECTED_MISSING
            and not any(
                diagnostic.empty_meaning is EmptyMeaning.UNEXPECTED_MISSING
                for diagnostic in self.diagnostics
            )
        ):
            raise ValueError(
                "unexpected-missing envelope requires a matching diagnostic"
            )


def _validate_source_freshness(
    source: SourceStamp, freshness: Freshness
) -> None:
    if source.data_time != freshness.data_time:
        raise ValueError("source and freshness data_time must match")
    if source.trading_date != freshness.trading_date:
        raise ValueError("source and freshness trading_date must match")
    if source.provider_published_at != freshness.provider_published_at:
        raise ValueError("source and freshness provider publication must match")
