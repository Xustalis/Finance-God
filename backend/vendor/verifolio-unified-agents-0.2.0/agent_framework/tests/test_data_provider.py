from __future__ import annotations

from datetime import datetime, timezone
from math import nan
from typing import Any

import pytest

import research_runtime.data_provider as data_provider
from research_runtime.config import PandaDataSettings
from research_runtime.data_provider import (
    DataDependencyError,
    DataResponseError,
    PandaDataEvidenceCompiler,
    PandaDataProvider,
)
from research_runtime.models import DataArtifact, DataQuery, PandaDataDataset


class FakeFrame:
    def __init__(self, records: list[dict[str, object]]) -> None:
        self._records = records

    def to_dict(self, *, orient: str) -> list[dict[str, object]]:
        assert orient == "records"
        return self._records


class FakePandaDataSdk:
    def __init__(self, frame: FakeFrame) -> None:
        self._frame = frame
        self.token_calls: list[dict[str, str]] = []
        self.market_calls: list[dict[str, Any]] = []

    def init_token(self, **kwargs: str) -> None:
        self.token_calls.append(kwargs)

    def get_market_data(self, **kwargs: Any) -> FakeFrame:
        self.market_calls.append(kwargs)
        return self._frame


def market_query() -> DataQuery:
    return DataQuery(
        identifier="bars-1",
        dataset=PandaDataDataset.MARKET_BARS,
        symbols=["600000.SH"],
        start_date="20260102",
        end_date="20260105",
    )


def market_records() -> list[dict[str, object]]:
    return [
        {
            "symbol": "600000.SH",
            "date": "20260102",
            "open": 10.0,
            "high": 10.5,
            "low": 9.8,
            "close": 10.0,
            "volume": 100,
        },
        {
            "symbol": "600000.SH",
            "date": "20260105",
            "open": 10.1,
            "high": 11.2,
            "low": 10.0,
            "close": 11.0,
            "volume": 120,
        },
    ]


@pytest.mark.parametrize("market_type", ("stock", "index", "future"))
def test_fetches_allowlisted_daily_bars_once_and_compiles_evidence(
    monkeypatch, market_type
) -> None:
    sdk = FakePandaDataSdk(FakeFrame(market_records()))
    monkeypatch.setattr(data_provider, "import_module", lambda _name: sdk)
    provider = PandaDataProvider(PandaDataSettings(username="user", password="password"))

    query = market_query().model_copy(update={"market_type": market_type})
    artifact = provider.fetch(query)
    second_artifact = provider.fetch(query)
    evidence = PandaDataEvidenceCompiler().compile(artifact)

    assert len(sdk.token_calls) == 1
    assert sdk.market_calls[0]["symbol"] == "600000.SH"
    assert sdk.market_calls[0]["type"] == market_type
    assert artifact.row_count == 2
    assert second_artifact.row_count == 2
    assert evidence.identifier == "PD_BARS-1"
    assert "change=10.00%" in evidence.excerpt


def test_fails_explicitly_when_optional_sdk_is_missing(monkeypatch) -> None:
    def missing_sdk(_name: str) -> Any:
        raise ModuleNotFoundError("panda_data")

    monkeypatch.setattr(data_provider, "import_module", missing_sdk)
    provider = PandaDataProvider(PandaDataSettings(username="user", password="password"))

    with pytest.raises(DataDependencyError, match="panda_data is not installed"):
        provider.fetch(market_query())


def test_rejects_empty_or_incomplete_upstream_responses(monkeypatch) -> None:
    sdk = FakePandaDataSdk(FakeFrame([]))
    monkeypatch.setattr(data_provider, "import_module", lambda _name: sdk)
    provider = PandaDataProvider(PandaDataSettings(username="user", password="password"))

    with pytest.raises(DataResponseError, match="returned no rows"):
        provider.fetch(market_query())

    sdk = FakePandaDataSdk(FakeFrame([{"date": "20260102", "close": 10.0}]))
    monkeypatch.setattr(data_provider, "import_module", lambda _name: sdk)
    provider = PandaDataProvider(PandaDataSettings(username="user", password="password"))

    with pytest.raises(DataResponseError, match="missing columns"):
        provider.fetch(market_query())


@pytest.mark.parametrize(
    ("start_date", "end_date", "message"),
    [
        ("20260105", "20260102", "start_date must not be later"),
        ("20200101", "20260103", "five-year limit"),
    ],
)
def test_validates_pandadata_date_ranges_before_sdk_access(
    start_date: str, end_date: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        DataQuery(
            identifier="bars-1",
            dataset=PandaDataDataset.MARKET_BARS,
            symbols=["600000.SH"],
            start_date=start_date,
            end_date=end_date,
        )


def test_evidence_labels_non_finite_values_as_unavailable() -> None:
    query = DataQuery(
        identifier="lhb-1",
        dataset=PandaDataDataset.LHB_LIST,
        start_date="20260102",
        end_date="20260102",
    )
    artifact = DataArtifact(
        provider="fake",
        query=query,
        retrieved_at=datetime.now(timezone.utc),
        row_count=1,
        columns=["symbol", "date", "amount", "change_rate", "turnover"],
        records=[
            {
                "symbol": "600000.SH",
                "date": "20260102",
                "amount": 1.0,
                "change_rate": nan,
                "turnover": 1.0,
            }
        ],
    )

    evidence = PandaDataEvidenceCompiler().compile(artifact)

    assert "no finite values" in evidence.excerpt
