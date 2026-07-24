"""Injected publication-state decisions for fail-closed market-data access."""

from __future__ import annotations

from datetime import datetime, time
from typing import Protocol
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from .contracts import (
    DataCategory,
    DataEnvelope,
    DataFrequency,
    FreshnessStatus,
    InstrumentId,
    MarketType,
    NormalizedCalendarDay,
    ReleaseState,
)
from .errors import MarketDataResponseError
from .instruments import (
    DEFAULT_INSTRUMENT_MASTER_IDENTITY,
    DEFAULT_INSTRUMENT_MASTER_VERSION,
)


_MARKET_ZONES = {
    "CN": ZoneInfo("Asia/Shanghai"),
    "HK": ZoneInfo("Asia/Hong_Kong"),
    "US": ZoneInfo("America/New_York"),
}


class PublishedStateDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    state: ReleaseState
    trading_date: str = Field(pattern=r"^\d{8}$")
    provider_published_at: datetime | None = None
    evidence_ref: str = Field(min_length=1, max_length=240)
    reason: str = Field(min_length=1, max_length=240)


class PublishedStatePort(Protocol):
    def evaluate(
        self,
        *,
        instrument: InstrumentId,
        category: DataCategory,
        frequency: DataFrequency,
        trading_date: str,
        observed_at: datetime,
    ) -> PublishedStateDecision: ...

    def probe(self, observed_at: datetime) -> None: ...


class FailClosedPublishedState:
    """Default until a trading-calendar publication feed is injected."""

    def evaluate(
        self,
        *,
        instrument: InstrumentId,
        category: DataCategory,
        frequency: DataFrequency,
        trading_date: str,
        observed_at: datetime,
    ) -> PublishedStateDecision:
        del instrument, category, frequency, observed_at
        return PublishedStateDecision(
            state=ReleaseState.UNKNOWN,
            trading_date=trading_date,
            evidence_ref="published-state:unconfigured",
            reason="no published-state/calendar adapter is configured",
        )

    def probe(self, observed_at: datetime) -> None:
        del observed_at
        raise MarketDataResponseError(
            "published-state/calendar adapter is not configured"
        )


class StaticPublishedState:
    """Explicit test/dev decision; callers choose the state and evidence."""

    def __init__(self, state: ReleaseState) -> None:
        self._state = state

    def evaluate(
        self,
        *,
        instrument: InstrumentId,
        category: DataCategory,
        frequency: DataFrequency,
        trading_date: str,
        observed_at: datetime,
    ) -> PublishedStateDecision:
        del instrument, category, frequency
        return PublishedStateDecision(
            state=self._state,
            trading_date=trading_date,
            provider_published_at=(
                observed_at if self._state is ReleaseState.RELEASED else None
            ),
            evidence_ref="published-state:static-injected",
            reason="explicit injected publication state",
        )

    def probe(self, observed_at: datetime) -> None:
        del observed_at


class CalendarDataPort(Protocol):
    def fetch_calendar(
        self,
        *,
        market: MarketType,
        start_date: str,
        end_date: str,
    ) -> DataEnvelope[NormalizedCalendarDay]: ...


class PandaCalendarPublishedState:
    """Calendar-backed release policy for normalized PandaData server composition."""

    def __init__(
        self,
        calendar: CalendarDataPort,
        *,
        instrument_master_identity: str = DEFAULT_INSTRUMENT_MASTER_IDENTITY,
        instrument_master_version: str = DEFAULT_INSTRUMENT_MASTER_VERSION,
    ) -> None:
        self._calendar = calendar
        self._instrument_master_identity = instrument_master_identity
        self._instrument_master_version = instrument_master_version

    def evaluate(
        self,
        *,
        instrument: InstrumentId,
        category: DataCategory,
        frequency: DataFrequency,
        trading_date: str,
        observed_at: datetime,
    ) -> PublishedStateDecision:
        calendar_day = self._calendar_day(instrument.market, trading_date)
        evidence_ref = (
            f"PandaData:get_trade_cal:{instrument.market.value}:{trading_date}"
        )
        if calendar_day.freshness.status is not FreshnessStatus.CURRENT:
            return PublishedStateDecision(
                state=ReleaseState.UNKNOWN,
                trading_date=trading_date,
                evidence_ref=evidence_ref,
                reason=(
                    "authoritative trading calendar freshness is "
                    f"{calendar_day.freshness.status.value}"
                ),
            )
        if calendar_day.freshness.release_state is not ReleaseState.RELEASED:
            return PublishedStateDecision(
                state=ReleaseState.UNKNOWN,
                trading_date=trading_date,
                evidence_ref=evidence_ref,
                reason="authoritative trading calendar release state is not released",
            )
        if not calendar_day.is_open:
            return PublishedStateDecision(
                state=ReleaseState.CLOSED_PENDING,
                trading_date=trading_date,
                evidence_ref=evidence_ref,
                reason="authoritative trading calendar marks the date closed",
            )
        local_now = observed_at.astimezone(_MARKET_ZONES[instrument.market.value])
        local_date = local_now.strftime("%Y%m%d")
        if trading_date < local_date:
            state = ReleaseState.RELEASED
            reason = "prior open trading date is released"
        elif trading_date > local_date:
            state = ReleaseState.UNKNOWN
            reason = "future trading date cannot be released"
        else:
            state, reason = _today_release(
                instrument,
                category,
                frequency,
                local_now.timetz().replace(tzinfo=None),
            )
        return PublishedStateDecision(
            state=state,
            trading_date=trading_date,
            evidence_ref=evidence_ref,
            reason=reason,
        )

    def probe(self, observed_at: datetime) -> None:
        trading_date = observed_at.astimezone(_MARKET_ZONES["CN"]).strftime("%Y%m%d")
        calendar_day = self._calendar_day(MarketType.CN, trading_date)
        if (
            calendar_day.freshness.status is not FreshnessStatus.CURRENT
            or calendar_day.freshness.release_state is not ReleaseState.RELEASED
        ):
            raise MarketDataResponseError(
                "authoritative trading calendar is not currently released",
                endpoint="get_trade_cal",
            )

    def _calendar_day(
        self, market: MarketType, trading_date: str
    ) -> NormalizedCalendarDay:
        envelope = self._calendar.fetch_calendar(
            market=market,
            start_date=trading_date,
            end_date=trading_date,
        )
        if envelope.diagnostics:
            raise MarketDataResponseError(
                "trading calendar returned quality diagnostics",
                endpoint="get_trade_cal",
            )
        if len(envelope.items) != 1:
            raise MarketDataResponseError(
                "trading calendar did not return exactly one normalized day",
                endpoint="get_trade_cal",
            )
        item = envelope.items[0]
        if not isinstance(item, NormalizedCalendarDay):
            raise MarketDataResponseError(
                "trading calendar returned a non-canonical normalized item",
                endpoint="get_trade_cal",
            )
        source = item.source
        if item.market is not market or item.trade_date != trading_date:
            raise MarketDataResponseError(
                "trading calendar identity does not match the requested market/date",
                endpoint="get_trade_cal",
            )
        if (
            source.provider != "PandaData"
            or source.endpoint != "get_trade_cal"
            or source.frequency is not DataFrequency.DAILY
            or source.trading_date != trading_date
        ):
            raise MarketDataResponseError(
                "trading calendar source evidence does not match the request",
                endpoint="get_trade_cal",
            )
        if (
            source.instrument_master_identity != self._instrument_master_identity
            or source.instrument_master_version != self._instrument_master_version
        ):
            raise MarketDataResponseError(
                "trading calendar instrument-master evidence is not authoritative",
                endpoint="get_trade_cal",
            )
        if (
            item.freshness.data_time != source.data_time
            or item.freshness.trading_date != trading_date
            or item.freshness.provider_published_at != source.provider_published_at
        ):
            raise MarketDataResponseError(
                "trading calendar freshness evidence conflicts with its source",
                endpoint="get_trade_cal",
            )
        return item


def _today_release(
    instrument: InstrumentId,
    category: DataCategory,
    frequency: DataFrequency,
    local_time: time,
) -> tuple[ReleaseState, str]:
    if category is DataCategory.SNAPSHOT or frequency is DataFrequency.MINUTE_1:
        open_time = time(9, 30)
        if local_time >= open_time:
            return ReleaseState.RELEASED, "intraday publication window has opened"
        return ReleaseState.CLOSED_PENDING, "intraday publication window has not opened"
    close_time = {
        "CN": time(16, 0),
        "HK": time(17, 0),
        "US": time(18, 0),
    }[instrument.market.value]
    if local_time >= close_time:
        return ReleaseState.RELEASED, "closed-session publication window has passed"
    return ReleaseState.CLOSED_PENDING, "closed-session dataset is not yet released"
