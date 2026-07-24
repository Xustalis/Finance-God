"""FMP stable-API compatibility runner for FinRobot's financial-data processor."""

from __future__ import annotations

import argparse
import importlib.util
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, Protocol

import pandas as pd
import requests

from .config import FmpSettings

_FMP_STABLE_BASE_URL = "https://financialmodelingprep.com/stable"
_FINANCIAL_ENDPOINTS = {
    "income_statement": "income-statement",
    "balance_sheet": "balance-sheet-statement",
    "cash_flow": "cash-flow-statement",
    "ratios": "ratios",
    "key_metrics": "key-metrics",
}


class FinRobotCompatibilityError(RuntimeError):
    """Raised when stable FMP data cannot be converted for FinRobot's processor."""


class HttpResponse(Protocol):
    status_code: int

    def json(self) -> object: ...


HttpGet = Callable[..., HttpResponse]


class FmpStableClient:
    """Minimal read-only FMP stable client that never logs credential-bearing URLs."""

    def __init__(self, api_key: str, http_get: HttpGet = requests.get) -> None:
        self._api_key = api_key
        self._http_get = http_get

    def financial_data(
        self, ticker: str, *, period: Literal["annual", "quarterly"], limit: int
    ) -> dict[str, pd.DataFrame]:
        return {
            name: self._fetch(endpoint, ticker=ticker, period=period, limit=limit)
            for name, endpoint in _FINANCIAL_ENDPOINTS.items()
        }

    def _fetch(self, endpoint: str, *, ticker: str, period: str, limit: int) -> pd.DataFrame:
        response = self._http_get(
            f"{_FMP_STABLE_BASE_URL}/{endpoint}",
            params={
                "symbol": ticker,
                "period": period,
                "limit": limit,
                "apikey": self._api_key,
            },
            timeout=20,
        )
        if response.status_code != 200:
            raise FinRobotCompatibilityError(
                f"FMP stable {endpoint} returned HTTP {response.status_code}"
            )
        payload = response.json()
        if not isinstance(payload, list) or not payload:
            raise FinRobotCompatibilityError(f"FMP stable {endpoint} returned no rows")
        rows = [_normalise_row(row, endpoint) for row in payload if isinstance(row, dict)]
        if not rows:
            raise FinRobotCompatibilityError(f"FMP stable {endpoint} returned invalid rows")
        return pd.DataFrame(rows)


def _normalise_row(row: dict[str, Any], endpoint: str) -> dict[str, Any]:
    normalised = dict(row)
    date = str(normalised.get("date", ""))
    if len(date) < 4 or not date[:4].isdigit():
        raise FinRobotCompatibilityError(f"FMP stable {endpoint} row has no usable date")
    normalised["year"] = int(date[:4])
    return normalised


def _load_processor(finrobot_source: Path):
    processor_path = finrobot_source / "modules" / "financial_data_processor.py"
    spec = importlib.util.spec_from_file_location("verifolio_finrobot_processor", processor_path)
    if spec is None or spec.loader is None:
        raise FinRobotCompatibilityError("FinRobot financial-data processor could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_compatibility_analysis(
    *,
    settings: FmpSettings,
    ticker: str,
    period: Literal["annual", "quarterly"],
    years_limit: int,
    finrobot_source: Path,
    output_dir: Path,
    client: FmpStableClient | None = None,
) -> Path:
    """Fetch current FMP data and pass it to FinRobot's local metrics transformer."""

    data = (client or FmpStableClient(settings.api_key)).financial_data(
        ticker, period=period, limit=years_limit
    )
    processor = _load_processor(finrobot_source)
    historical = processor.extract_historical_metrics_from_api_data(data)
    if historical is None or historical.empty:
        raise FinRobotCompatibilityError("FinRobot returned no historical metrics")
    actual_years = [column for column in historical.columns if str(column).endswith("A")]
    if not actual_years:
        raise FinRobotCompatibilityError("FinRobot metrics contain no actual-year columns")
    latest_year = max(actual_years)
    forecast = processor.calculate_growth_and_forecasts(
        historical,
        {
            "revenue_base_year": latest_year,
            "revenue_growth_assumptions": {"2025E": 0.05, "2026E": 0.06, "2027E": 0.04},
            "ebitda_growth_factor": 1.05,
            "margin_improvement": {"Contribution Margin": 0.01, "EBITDA Margin": 0.01},
            "sga_margin_change": -0.005,
        },
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "financial_metrics_and_forecasts.csv"
    forecast.to_csv(output_path, index=False)
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--years-limit", type=int, required=True)
    parser.add_argument("--period", choices=("annual", "quarterly"), required=True)
    parser.add_argument("--finrobot-source", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    run_compatibility_analysis(
        settings=FmpSettings.from_environment(),
        ticker=arguments.ticker,
        years_limit=arguments.years_limit,
        period=arguments.period,
        finrobot_source=arguments.finrobot_source,
        output_dir=arguments.output_dir,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
