from __future__ import annotations

import pytest
from research_runtime.models import DataQuery, PandaDataDataset

from finance_god.orchestration.market_data_provider import FinanceGodMarketDataProvider

from .conftest import FakeSDK, adapter


@pytest.mark.parametrize(
    ("dataset", "symbols", "response", "expected_columns"),
    [
        (
            PandaDataDataset.MARGIN,
            ["000001.SZ"],
            [
                {
                    "symbol": "000001.SZ",
                    "date": "20260722",
                    "total_balance": 100.0,
                    "short_balance": 10.0,
                }
            ],
            {"date", "total_balance", "short_balance"},
        ),
        (
            PandaDataDataset.LHB_LIST,
            [],
            [
                {
                    "symbol": "000001.SZ",
                    "date": "20260722",
                    "amount": 10.0,
                    "change_rate": 0.02,
                    "turnover": 0.03,
                }
            ],
            {"date", "amount", "change_rate"},
        ),
        (
            PandaDataDataset.FUTURE_DOMINANT_CORR,
            ["RB", "JM"],
            {"RB:JM": 0.4},
            {"pair", "correlation"},
        ),
        (
            PandaDataDataset.OPTION_IMPLIED_VOLATILITY,
            [],
            [{"date": "20260722", "symbol": "OPT", "implied_volatility": 25.0}],
            {"date", "implied_volatility"},
        ),
        (
            PandaDataDataset.OPTION_UNDERLYING_VOLATILITY,
            ["510300.SH"],
            [
                {
                    "date": "20260722",
                    "symbol": "510300.SH",
                    "close": 4.2,
                    "historical_volatility": 0.19,
                    "period": 30,
                }
            ],
            {"date", "historical_volatility"},
        ),
    ],
)
def test_provider_converts_verified_monitor_data_to_agent_artifacts(
    dataset: PandaDataDataset,
    symbols: list[str],
    response: object,
    expected_columns: set[str],
) -> None:
    sdk = FakeSDK()
    endpoint = {
        PandaDataDataset.MARGIN: "get_margin",
        PandaDataDataset.LHB_LIST: "get_lhb_list",
        PandaDataDataset.FUTURE_DOMINANT_CORR: "get_future_dominant_corr",
        PandaDataDataset.OPTION_IMPLIED_VOLATILITY: "get_option_implied_volatility",
        PandaDataDataset.OPTION_UNDERLYING_VOLATILITY: "get_option_underlying_volatility",
    }[dataset]
    sdk.responses[endpoint] = response

    result = FinanceGodMarketDataProvider(adapter(sdk)).fetch(
        DataQuery(
            identifier=dataset.value,
            dataset=dataset,
            symbols=symbols,
            start_date="20260722",
            end_date="20260723",
        )
    )

    assert expected_columns.issubset(result.columns)
    assert result.provider == "Finance-God/PandaData"
    assert result.records


def test_provider_uses_normalized_index_bars_for_market_regime() -> None:
    sdk = FakeSDK()
    sdk.responses["get_index_daily"] = [
        {
            "symbol": "000300.SH",
            "date": "20260723",
            "open": 100.0,
            "high": 103.0,
            "low": 99.0,
            "close": 102.0,
            "volume": 1000,
        },
        {
            "symbol": "000300.SH",
            "date": "20260722",
            "open": 99.0,
            "high": 101.0,
            "low": 98.0,
            "close": 100.0,
            "volume": 1000,
        },
    ]

    result = FinanceGodMarketDataProvider(adapter(sdk)).fetch(
        DataQuery(
            identifier="regime-index",
            dataset=PandaDataDataset.MARKET_BARS,
            symbols=["000300.SH"],
            start_date="20260722",
            end_date="20260723",
            market_type="index",
        )
    )

    assert [record["close"] for record in result.records] == [102.0, 100.0]
