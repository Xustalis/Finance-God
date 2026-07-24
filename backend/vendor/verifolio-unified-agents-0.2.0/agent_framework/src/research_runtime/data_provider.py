"""Fetch-only PandaData adapter and deterministic evidence compiler."""

from __future__ import annotations

from datetime import datetime, timezone
from importlib import import_module
from math import isfinite
from statistics import mean
from typing import Any, Protocol

from .config import PandaDataSettings
from .models import DataArtifact, DataQuery, EvidenceRecord, PandaDataDataset


class DataDependencyError(RuntimeError):
    """Raised when the optional PandaData SDK is unavailable."""


class DataResponseError(RuntimeError):
    """Raised when an upstream response is empty or violates the expected schema."""


class DataProvider(Protocol):
    """A data source that can return one audited artifact for one allowed query."""

    def fetch(self, query: DataQuery) -> DataArtifact: ...


_DEFAULT_FIELDS: dict[PandaDataDataset, list[str]] = {
    PandaDataDataset.MARKET_BARS: ["symbol", "date", "open", "high", "low", "close", "volume"],
    PandaDataDataset.MARGIN: ["symbol", "date", "total_balance", "short_balance"],
    PandaDataDataset.LHB_LIST: ["symbol", "date", "amount", "change_rate", "turnover"],
    PandaDataDataset.FUTURE_DOMINANT_CORR: ["pair", "correlation"],
    PandaDataDataset.OPTION_IMPLIED_VOLATILITY: ["date", "symbol", "implied_volatility"],
    PandaDataDataset.OPTION_UNDERLYING_VOLATILITY: [
        "date",
        "symbol",
        "close",
        "period",
        "historical_volatility",
    ],
}


class PandaDataProvider:
    """A white-listed, read-only adapter around the optional ``panda_data`` SDK."""

    def __init__(self, settings: PandaDataSettings):
        self._settings = settings
        self._authenticated = False

    def fetch(self, query: DataQuery) -> DataArtifact:
        sdk = self._sdk()
        self._authenticate(sdk)
        records = self._to_records(self._request(sdk, query), query.dataset)
        if not records:
            raise DataResponseError(f"PandaData returned no rows for {query.identifier}.")
        columns = sorted({key for record in records for key in record})
        required_columns = set(query.fields or _DEFAULT_FIELDS[query.dataset])
        missing_columns = sorted(required_columns.difference(columns))
        if missing_columns:
            raise DataResponseError(
                f"PandaData response for {query.identifier} is missing columns: "
                f"{', '.join(missing_columns)}"
            )
        incomplete_rows = [
            index for index, record in enumerate(records) if required_columns.difference(record)
        ]
        if incomplete_rows:
            raise DataResponseError(
                f"PandaData response for {query.identifier} has incomplete rows: "
                f"{', '.join(str(index) for index in incomplete_rows[:5])}"
            )
        return DataArtifact(
            provider="pandadata",
            query=query,
            retrieved_at=datetime.now(timezone.utc),
            row_count=len(records),
            columns=columns,
            records=records,
        )

    @staticmethod
    def _sdk() -> Any:
        try:
            return import_module("panda_data")
        except ModuleNotFoundError as error:
            raise DataDependencyError(
                "panda_data is not installed. Install the optional dependency with "
                "`pip install -e '.[panda]'`."
            ) from error

    def _authenticate(self, sdk: Any) -> None:
        if self._authenticated:
            return
        arguments: dict[str, str] = {
            "username": self._settings.username,
            "password": self._settings.password,
        }
        if self._settings.base_url:
            arguments["base_url"] = self._settings.base_url
        sdk.init_token(**arguments)
        self._authenticated = True

    @staticmethod
    def _symbol_argument(query: DataQuery) -> str | list[str]:
        if not query.symbols:
            return ""
        if len(query.symbols) == 1:
            return query.symbols[0]
        return query.symbols

    def _request(self, sdk: Any, query: DataQuery) -> Any:
        fields = query.fields or _DEFAULT_FIELDS[query.dataset]
        symbol = self._symbol_argument(query)
        if query.dataset == PandaDataDataset.MARKET_BARS:
            return sdk.get_market_data(
                symbol=symbol,
                start_date=query.start_date,
                end_date=query.end_date,
                type=query.market_type,
                fields=fields,
                indicator="",
                st=True,
            )
        if query.dataset == PandaDataDataset.MARGIN:
            return sdk.get_margin(
                symbol=symbol,
                start_date=query.start_date,
                end_date=query.end_date,
                margin_type="stock",
                fields=fields,
            )
        if query.dataset == PandaDataDataset.LHB_LIST:
            return sdk.get_lhb_list(
                start_date=query.start_date,
                end_date=query.end_date,
                type="",
                symbol=symbol if query.symbols else "",
                fields=fields,
            )
        if query.dataset == PandaDataDataset.FUTURE_DOMINANT_CORR:
            return sdk.get_future_dominant_corr(
                symbol=query.symbols,
                start_date=query.start_date,
                end_date=query.end_date,
            )
        if query.dataset == PandaDataDataset.OPTION_IMPLIED_VOLATILITY:
            return sdk.get_option_implied_volatility(
                start_date=query.start_date,
                end_date=query.end_date,
                symbol=symbol if query.symbols else "",
                fields=fields,
            )
        if query.dataset == PandaDataDataset.OPTION_UNDERLYING_VOLATILITY:
            return sdk.get_option_underlying_volatility(
                start_date=query.start_date,
                end_date=query.end_date,
                symbol=symbol,
                period=query.volatility_period,
                fields=fields,
            )
        raise ValueError(f"Unsupported PandaData dataset: {query.dataset.value}")

    @staticmethod
    def _to_records(response: Any, dataset: PandaDataDataset) -> list[dict[str, object]]:
        if hasattr(response, "to_dict"):
            records = response.to_dict(orient="records")
        elif isinstance(response, list):
            records = response
        elif isinstance(response, dict) and dataset == PandaDataDataset.FUTURE_DOMINANT_CORR:
            records = [{"pair": pair, "correlation": value} for pair, value in response.items()]
        else:
            raise DataResponseError(
                f"PandaData returned an unsupported response type for {dataset.value}."
            )
        if not all(isinstance(record, dict) for record in records):
            raise DataResponseError(f"PandaData returned non-record rows for {dataset.value}.")
        return records


class PandaDataEvidenceCompiler:
    """Compile a bounded, reproducible evidence record from one fetched artifact."""

    def compile(self, artifact: DataArtifact) -> EvidenceRecord:
        query = artifact.query
        return EvidenceRecord(
            identifier=f"PD_{query.identifier.upper()}",
            source=f"PandaData {query.dataset.value} ({query.identifier})",
            excerpt=(
                f"Fetch-only PandaData query {query.identifier}: dataset={query.dataset.value}; "
                f"period={query.start_date}-{query.end_date}; rows={artifact.row_count}; "
                f"{self._summary(artifact)}"
            ),
        )

    def _summary(self, artifact: DataArtifact) -> str:
        rows = artifact.records
        dataset = artifact.query.dataset
        if dataset == PandaDataDataset.MARKET_BARS:
            return self._market_bar_summary(rows)
        if dataset == PandaDataDataset.FUTURE_DOMINANT_CORR:
            return self._numeric_summary(rows, "correlation", "correlation")
        if dataset == PandaDataDataset.OPTION_IMPLIED_VOLATILITY:
            return self._numeric_summary(rows, "implied_volatility", "implied volatility")
        if dataset == PandaDataDataset.OPTION_UNDERLYING_VOLATILITY:
            return self._numeric_summary(rows, "historical_volatility", "historical volatility")
        if dataset == PandaDataDataset.MARGIN:
            return self._numeric_summary(rows, "total_balance", "margin balance")
        return self._numeric_summary(rows, "change_rate", "LHB change rate")

    @staticmethod
    def _market_bar_summary(rows: list[dict[str, object]]) -> str:
        ordered = sorted(rows, key=lambda row: str(row["date"]))
        first = ordered[0]
        last = ordered[-1]
        first_close = PandaDataEvidenceCompiler._number(first["close"])
        last_close = PandaDataEvidenceCompiler._number(last["close"])
        if first_close is None or last_close is None:
            raise DataResponseError("market_bars evidence requires numeric close values.")
        change = (last_close - first_close) / abs(first_close) if first_close else None
        change_text = "n/a" if change is None else f"{change:.2%}"
        return (
            f"first_close={first_close:.6g} on {first['date']}; "
            f"last_close={last_close:.6g} on {last['date']}; change={change_text}"
        )

    @staticmethod
    def _numeric_summary(rows: list[dict[str, object]], field: str, label: str) -> str:
        values: list[float] = []
        for row in rows:
            value = PandaDataEvidenceCompiler._number(row[field])
            if value is not None:
                values.append(value)
        if not values:
            return f"{label}: no finite values"
        return f"{label}: mean={mean(values):.6g}; min={min(values):.6g}; max={max(values):.6g}"

    @staticmethod
    def _number(value: object) -> float | None:
        try:
            number = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        return number if isfinite(number) else None
