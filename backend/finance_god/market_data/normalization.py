"""Strict PandaData response normalization without fabricated defaults."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from itertools import pairwise
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from .capabilities import CAPABILITY_CATALOG_VERSION
from .contracts import (
    DataCategory,
    DataDiagnostic,
    DataEnvelope,
    DataFrequency,
    DiagnosticCode,
    DiagnosticSeverity,
    EmptyMeaning,
    InstrumentId,
    MarketType,
    NormalizedBar,
    NormalizedSnapshot,
    ReleaseState,
    SourceStamp,
)
from .errors import MarketDataResponseError
from .freshness import FreshnessPolicy
from .instruments import (
    DEFAULT_INSTRUMENT_MASTER_IDENTITY,
    DEFAULT_INSTRUMENT_MASTER_VERSION,
)

_MARKET_ZONES = {
    MarketType.CN: ZoneInfo("Asia/Shanghai"),
    MarketType.HK: ZoneInfo("Asia/Hong_Kong"),
    MarketType.US: ZoneInfo("America/New_York"),
}
_SNAPSHOT_REQUIRED = frozenset(
    {"symbol", "date", "open", "high", "low", "close", "volume"}
)
_BAR_REQUIRED = frozenset({"date", "open", "high", "low", "close", "volume"})


def diagnostic(
    *,
    code: DiagnosticCode,
    scope: str,
    message: str,
    endpoint: str | None,
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR,
    empty_meaning: EmptyMeaning = EmptyMeaning.NOT_EMPTY,
    retryable: bool = False,
    details: Mapping[str, str] | None = None,
) -> DataDiagnostic:
    safe_details = tuple(sorted((details or {}).items()))
    material = "|".join(
        (
            code.value,
            scope,
            endpoint or "",
            message,
            repr(safe_details),
        )
    )
    return DataDiagnostic(
        code=code,
        severity=severity,
        scope=scope,
        message=message,
        fingerprint=sha256(material.encode()).hexdigest(),
        empty_meaning=empty_meaning,
        retryable=retryable,
        endpoint=endpoint,
        details=safe_details,
    )


def records_from_frame(frame: Any, *, endpoint: str) -> list[dict[str, Any]]:
    if frame is None:
        return []
    if hasattr(frame, "to_dict"):
        records = frame.to_dict(orient="records")
    elif isinstance(frame, list):
        records = frame
    else:
        raise MarketDataResponseError(
            f"{endpoint} returned unsupported response type {type(frame).__name__}",
            endpoint=endpoint,
        )
    if not isinstance(records, list) or any(
        not isinstance(record, dict) for record in records
    ):
        raise MarketDataResponseError(
            f"{endpoint} returned a non-record response", endpoint=endpoint
        )
    return records


class PandaDataNormalizer:
    def __init__(
        self,
        freshness_policy: FreshnessPolicy,
        *,
        instrument_master_identity: str = DEFAULT_INSTRUMENT_MASTER_IDENTITY,
        instrument_master_version: str = DEFAULT_INSTRUMENT_MASTER_VERSION,
    ) -> None:
        self._freshness_policy = freshness_policy
        self._instrument_master_identity = instrument_master_identity
        self._instrument_master_version = instrument_master_version

    def snapshot(
        self,
        records: Iterable[dict[str, Any]],
        *,
        instrument: InstrumentId,
        endpoint: str,
        ingested_at: datetime,
        release_state: ReleaseState,
        expected_date: str | None = None,
        provider_published_at: datetime | None = None,
    ) -> DataEnvelope[NormalizedSnapshot]:
        rows = list(records)
        scope = instrument.symbol
        if not rows:
            return self._unexpected_empty(scope, endpoint)
        if any(not _SNAPSHOT_REQUIRED.issubset(row) for row in rows):
            return self._schema_failure(
                scope, endpoint, "snapshot response is missing required fields"
            )
        if any(
            str(row["symbol"]).upper() != instrument.provider_symbol for row in rows
        ):
            return self._conflict_failure(
                scope, endpoint, "snapshot response contains a different instrument"
            )
        if len(rows) != 1:
            return self._conflict_failure(
                scope,
                endpoint,
                "snapshot response must contain exactly one row",
            )
        selected = rows[0]
        if (
            expected_date is not None
            and _compact_date(selected["date"]) != expected_date
        ):
            return self._conflict_failure(
                scope, endpoint, "snapshot date is outside requested trading date"
            )
        try:
            data_time = _parse_data_time(selected["date"], instrument.market)
            source = self._source(
                endpoint=endpoint,
                data_time=data_time,
                ingested_at=ingested_at,
                frequency=DataFrequency.SNAPSHOT,
                provider_published_at=provider_published_at or data_time,
            )
            freshness = self._freshness_policy.evaluate(
                market=instrument.market,
                category=DataCategory.SNAPSHOT,
                frequency=DataFrequency.SNAPSHOT,
                data_time=data_time,
                trading_date=data_time.strftime("%Y%m%d"),
                provider_published_at=provider_published_at or data_time,
                evaluated_at=ingested_at,
                release_state=release_state,
            )
            item = NormalizedSnapshot(
                instrument=instrument,
                source=source,
                freshness=freshness,
                last=_decimal(selected["close"], field="close"),
                open=_decimal(selected["open"], field="open"),
                high=_decimal(selected["high"], field="high"),
                low=_decimal(selected["low"], field="low"),
                previous_close=_optional_decimal(
                    selected.get("pre_close", selected.get("actual_pre_close")),
                    field="previous_close",
                ),
                volume=_decimal(selected["volume"], field="volume"),
                amount=_optional_decimal(selected.get("amount"), field="amount"),
            )
        except (KeyError, ValueError, InvalidOperation, ValidationError) as error:
            return self._schema_failure(
                scope,
                endpoint,
                f"snapshot schema validation failed: {type(error).__name__}",
            )
        return DataEnvelope((item,), (), EmptyMeaning.NOT_EMPTY)

    def bars(
        self,
        records: Iterable[dict[str, Any]],
        *,
        instrument: InstrumentId,
        endpoint: str,
        frequency: DataFrequency,
        ingested_at: datetime,
        release_state: ReleaseState,
        start_date: str,
        end_date: str,
        limit: int,
        provider_published_at: datetime | None = None,
    ) -> DataEnvelope[NormalizedBar]:
        rows = list(records)
        scope = f"{instrument.symbol}:{frequency.value}"
        if not rows:
            return self._unexpected_empty(scope, endpoint)
        required = _BAR_REQUIRED | {"symbol"}
        if any(not required.issubset(row) for row in rows):
            return self._schema_failure(
                scope, endpoint, "bar response is missing required fields"
            )
        if any(
            str(row["symbol"]).upper() != instrument.provider_symbol for row in rows
        ):
            return self._conflict_failure(
                scope, endpoint, "bar response contains a different instrument"
            )
        if any(not _matches_frequency(row, frequency) for row in rows):
            return self._schema_failure(
                scope,
                endpoint,
                "bar response timestamp does not match requested granularity",
            )
        try:
            parsed = [
                (_parse_data_time(_bar_time(row), instrument.market), row)
                for row in rows
            ]
        except (KeyError, ValueError):
            return self._schema_failure(
                scope, endpoint, "bar response contains an invalid timestamp"
            )
        if any(
            not start_date <= timestamp.strftime("%Y%m%d") <= end_date
            for timestamp, _ in parsed
        ):
            return self._conflict_failure(
                scope, endpoint, "bar response date is outside request range"
            )
        timestamps = [timestamp for timestamp, _ in parsed]
        descending = endpoint in {
            "get_stock_min",
            "get_stock_rt_min",
            "get_stock_daily",
            "get_hk_daily",
            "get_us_daily",
            "get_index_daily",
        }
        if any(
            (current >= previous if descending else current <= previous)
            for previous, current in pairwise(timestamps)
        ):
            return self._schema_failure(
                scope,
                endpoint,
                "bar response contains duplicate or out-of-order timestamps",
            )
        try:
            selected = parsed[:limit] if descending else parsed[-limit:]
            items = tuple(
                self._bar(
                    row,
                    timestamp=timestamp,
                    instrument=instrument,
                    endpoint=endpoint,
                    frequency=frequency,
                    ingested_at=ingested_at,
                    release_state=release_state,
                    provider_published_at=provider_published_at,
                )
                for timestamp, row in selected
            )
        except (ValueError, InvalidOperation, ValidationError) as error:
            return self._schema_failure(
                scope,
                endpoint,
                f"bar schema validation failed: {type(error).__name__}",
            )
        return DataEnvelope(items, (), EmptyMeaning.NOT_EMPTY)

    def _bar(
        self,
        row: dict[str, Any],
        *,
        timestamp: datetime,
        instrument: InstrumentId,
        endpoint: str,
        frequency: DataFrequency,
        ingested_at: datetime,
        release_state: ReleaseState,
        provider_published_at: datetime | None,
    ) -> NormalizedBar:
        publication_time = (
            provider_published_at
            if provider_published_at is not None
            else (timestamp if endpoint == "get_stock_rt_min" else None)
        )
        source = self._source(
            endpoint=endpoint,
            data_time=timestamp,
            ingested_at=ingested_at,
            frequency=frequency,
            provider_published_at=publication_time,
        )
        freshness = self._freshness_policy.evaluate(
            market=instrument.market,
            category=DataCategory.BAR,
            frequency=frequency,
            data_time=timestamp,
            trading_date=timestamp.strftime("%Y%m%d"),
            provider_published_at=publication_time,
            evaluated_at=ingested_at,
            release_state=release_state,
        )
        return NormalizedBar(
            instrument=instrument,
            source=source,
            freshness=freshness,
            open=_decimal(row["open"], field="open"),
            high=_decimal(row["high"], field="high"),
            low=_decimal(row["low"], field="low"),
            close=_decimal(row["close"], field="close"),
            volume=_decimal(row["volume"], field="volume"),
            amount=_optional_decimal(row.get("amount"), field="amount"),
        )

    def _source(
        self,
        *,
        endpoint: str,
        data_time: datetime,
        ingested_at: datetime,
        frequency: DataFrequency,
        provider_published_at: datetime | None,
    ) -> SourceStamp:
        return SourceStamp(
            endpoint=endpoint,
            instrument_master_identity=self._instrument_master_identity,
            instrument_master_version=self._instrument_master_version,
            data_time=data_time,
            trading_date=data_time.strftime("%Y%m%d"),
            provider_published_at=provider_published_at,
            ingested_at=ingested_at,
            frequency=frequency,
            capability_version=CAPABILITY_CATALOG_VERSION,
            verification="verified_once_research",
            evidence_ref=(
                "artifacts/pandadata-capabilities/verification-summary-v1.json"
            ),
        )

    @staticmethod
    def _unexpected_empty(scope: str, endpoint: str) -> DataEnvelope[Any]:
        issue = diagnostic(
            code=DiagnosticCode.UNEXPECTED_MISSING,
            scope=scope,
            message="PandaData returned no row for an expected market-data scope",
            endpoint=endpoint,
            empty_meaning=EmptyMeaning.UNEXPECTED_MISSING,
        )
        return DataEnvelope((), (issue,), EmptyMeaning.UNEXPECTED_MISSING)

    @staticmethod
    def _schema_failure(scope: str, endpoint: str, message: str) -> DataEnvelope[Any]:
        issue = diagnostic(
            code=DiagnosticCode.SCHEMA_DRIFT,
            scope=scope,
            message=message,
            endpoint=endpoint,
            empty_meaning=EmptyMeaning.UNEXPECTED_MISSING,
        )
        return DataEnvelope((), (issue,), EmptyMeaning.UNEXPECTED_MISSING)

    @staticmethod
    def _conflict_failure(scope: str, endpoint: str, message: str) -> DataEnvelope[Any]:
        issue = diagnostic(
            code=DiagnosticCode.CONFLICT,
            scope=scope,
            message=message,
            endpoint=endpoint,
            empty_meaning=EmptyMeaning.UNEXPECTED_MISSING,
        )
        return DataEnvelope((), (issue,), EmptyMeaning.UNEXPECTED_MISSING)


def valid_no_event(*, scope: str, endpoint: str, message: str) -> DataEnvelope[object]:
    issue = diagnostic(
        code=DiagnosticCode.VALID_NO_EVENT,
        scope=scope,
        message=message,
        endpoint=endpoint,
        severity=DiagnosticSeverity.INFO,
        empty_meaning=EmptyMeaning.VALID_NO_EVENT,
    )
    return DataEnvelope((), (issue,), EmptyMeaning.VALID_NO_EVENT)


def _compact_date(value: object) -> str:
    return "".join(character for character in str(value) if character.isdigit())[:8]


def _bar_time(record: Mapping[str, Any]) -> object:
    value = record.get("datetime")
    if value is not None and str(value).strip():
        return value
    return record["date"]


def _matches_frequency(record: Mapping[str, Any], frequency: DataFrequency) -> bool:
    raw = str(_bar_time(record)).strip()
    if frequency is DataFrequency.DAILY:
        if record.get("datetime") not in {None, ""}:
            return False
        return bool(
            re.fullmatch(r"\d{8}", raw) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw)
        )
    if frequency is DataFrequency.MINUTE_1:
        if not (
            re.fullmatch(r"\d{8} \d{2}:\d{2}:\d{2}", raw)
            or re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", raw)
            or re.fullmatch(
                r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{1,6}",
                raw,
            )
            or re.fullmatch(r"\d{14}", raw)
        ):
            return False
        try:
            parsed = _parse_data_time(raw, MarketType.CN)
        except ValueError:
            return False
        return parsed.second == 0 and parsed.microsecond == 0
    return False


def _parse_data_time(value: object, market: MarketType) -> datetime:
    raw = str(value).strip()
    if not raw:
        raise ValueError("data time is blank")
    formats = (
        "%Y%m%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y%m%d%H%M%S",
        "%Y%m%d",
        "%Y-%m-%d",
    )
    for format_value in formats:
        try:
            parsed = datetime.strptime(  # noqa: DTZ007
                raw,
                format_value,
            )
        except ValueError:
            continue
        return parsed.replace(tzinfo=_MARKET_ZONES[market])
    raise ValueError("unsupported data timestamp")


def _decimal(value: object, *, field: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{field} is missing")
    number = Decimal(str(value))
    if not number.is_finite() or number < 0:
        raise ValueError(f"{field} must be finite and non-negative")
    return number


def _optional_decimal(value: object, *, field: str) -> Decimal | None:
    if value is None or str(value).strip() == "":
        return None
    return _decimal(value, field=field)
