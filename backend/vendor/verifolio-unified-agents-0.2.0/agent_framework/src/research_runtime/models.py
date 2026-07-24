"""Data contracts for a constrained evidence-based research run."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, model_validator


class EvidenceRecord(BaseModel):
    identifier: str = Field(min_length=1, max_length=64)
    source: str = Field(min_length=1, max_length=256)
    excerpt: str = Field(min_length=1, max_length=4_000)


class PandaDataDataset(str, Enum):
    """Read-only PandaData datasets exposed to the research engine."""

    MARKET_BARS = "market_bars"
    MARGIN = "margin"
    LHB_LIST = "lhb_list"
    FUTURE_DOMINANT_CORR = "future_dominant_corr"
    OPTION_IMPLIED_VOLATILITY = "option_implied_volatility"
    OPTION_UNDERLYING_VOLATILITY = "option_underlying_volatility"


class PandaMonitorKind(str, Enum):
    """Deterministic, read-only monitors adapted from public Agent contracts."""

    CORRELATION_BREAK = "correlation_break"
    CROWDING_RISK = "crowding_risk"
    DERIVATIVES_IV_PREMIUM = "derivatives_iv_premium"
    MARKET_REGIME = "market_regime"


class DataQuery(BaseModel):
    """A validated, allowlisted PandaData query with no executable code path."""

    identifier: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    dataset: PandaDataDataset
    symbols: list[str] = Field(default_factory=list, max_length=32)
    start_date: str = Field(pattern=r"^\d{8}$")
    end_date: str = Field(pattern=r"^\d{8}$")
    market_type: str = Field(default="stock", pattern=r"^(stock|index|future)$")
    fields: list[str] = Field(default_factory=list, max_length=32)
    volatility_period: int = Field(default=30, ge=1, le=500)

    @model_validator(mode="after")
    def validate_date_range_and_dataset(self) -> DataQuery:
        try:
            start = datetime.strptime(self.start_date, "%Y%m%d").date()
            end = datetime.strptime(self.end_date, "%Y%m%d").date()
        except ValueError as error:
            raise ValueError("start_date and end_date must be valid YYYYMMDD dates") from error
        if start > end:
            raise ValueError("start_date must not be later than end_date")
        if self.dataset == PandaDataDataset.MARKET_BARS and (end - start).days > 5 * 366:
            raise ValueError("market_bars requests must not exceed PandaData's five-year limit")
        requires_symbols = {
            PandaDataDataset.MARKET_BARS,
            PandaDataDataset.FUTURE_DOMINANT_CORR,
            PandaDataDataset.OPTION_UNDERLYING_VOLATILITY,
        }
        if self.dataset in requires_symbols and not self.symbols:
            raise ValueError(f"{self.dataset.value} requires at least one symbol")
        if self.dataset == PandaDataDataset.OPTION_UNDERLYING_VOLATILITY and len(self.symbols) != 1:
            raise ValueError("option_underlying_volatility requires exactly one symbol")
        valid_volatility_periods = {5, 10, 30, 60, 90, 120, 180, 250, 500}
        if (
            self.dataset == PandaDataDataset.OPTION_UNDERLYING_VOLATILITY
            and self.volatility_period not in valid_volatility_periods
        ):
            raise ValueError(
                "option_underlying_volatility requires one of: "
                "5, 10, 30, 60, 90, 120, 180, 250, 500"
            )
        return self


class DataArtifact(BaseModel):
    """Fetched data plus safe audit metadata; raw records stay out of result serialization."""

    provider: str
    query: DataQuery
    retrieved_at: datetime
    row_count: int = Field(ge=1)
    columns: list[str] = Field(min_length=1)
    records: list[dict[str, object]] = Field(exclude=True)


class PandaMonitorRequest(BaseModel):
    """Validated inputs used to generate a bounded PandaData monitor query plan."""

    kind: PandaMonitorKind
    subject: str = Field(min_length=1, max_length=256)
    start_date: str = Field(pattern=r"^\d{8}$")
    end_date: str = Field(pattern=r"^\d{8}$")
    symbol: str | None = Field(default=None, max_length=64)
    index_symbol: str = Field(default="000300.SH", min_length=1, max_length=64)
    option_symbols: list[str] = Field(default_factory=list, max_length=32)
    option_underlying: str | None = Field(default=None, max_length=64)
    future_symbols: list[str] = Field(default_factory=list, max_length=32)
    baseline_start_date: str | None = Field(default=None, pattern=r"^\d{8}$")
    baseline_end_date: str | None = Field(default=None, pattern=r"^\d{8}$")
    volatility_period: int = Field(default=30, ge=1, le=500)

    @model_validator(mode="after")
    def validate_monitor_request(self) -> PandaMonitorRequest:
        self._validate_dates(self.start_date, self.end_date, "current")
        valid_periods = {5, 10, 30, 60, 90, 120, 180, 250, 500}
        if self.volatility_period not in valid_periods:
            raise ValueError(
                "volatility_period must be one of: 5, 10, 30, 60, 90, 120, 180, 250, 500"
            )
        if self.kind == PandaMonitorKind.CORRELATION_BREAK:
            if not self.future_symbols:
                raise ValueError("correlation_break requires future_symbols")
            if bool(self.baseline_start_date) != bool(self.baseline_end_date):
                raise ValueError(
                    "correlation baseline requires both baseline_start_date and baseline_end_date"
                )
            if self.baseline_start_date and self.baseline_end_date:
                self._validate_dates(self.baseline_start_date, self.baseline_end_date, "baseline")
        if self.kind in {PandaMonitorKind.CROWDING_RISK, PandaMonitorKind.MARKET_REGIME}:
            if not self.symbol:
                raise ValueError(f"{self.kind.value} requires symbol for the funding observation")
        if (
            self.kind
            in {
                PandaMonitorKind.DERIVATIVES_IV_PREMIUM,
                PandaMonitorKind.MARKET_REGIME,
            }
            and not self.option_underlying
        ):
            raise ValueError(f"{self.kind.value} requires option_underlying")
        return self

    @staticmethod
    def _validate_dates(start_date: str, end_date: str, name: str) -> None:
        try:
            start = datetime.strptime(start_date, "%Y%m%d").date()
            end = datetime.strptime(end_date, "%Y%m%d").date()
        except ValueError as error:
            raise ValueError(f"{name} dates must be valid YYYYMMDD dates") from error
        if start > end:
            raise ValueError(f"{name} start_date must not be later than end_date")


class PandaMonitorSnapshot(BaseModel):
    """A deterministic monitor conclusion, not an investment recommendation."""

    kind: PandaMonitorKind
    state: str
    confidence: str
    metrics: dict[str, float | int | str | None]
    limitations: list[str] = Field(default_factory=list, max_length=10)

