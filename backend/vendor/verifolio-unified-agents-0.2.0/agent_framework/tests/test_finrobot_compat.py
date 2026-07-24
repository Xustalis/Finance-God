from __future__ import annotations

from typing import Any

import pytest

from research_runtime.finrobot_compat import FinRobotCompatibilityError, FmpStableClient


class FakeResponse:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        return self._payload


def test_stable_client_normalises_fiscal_year_from_date() -> None:
    calls: list[dict[str, Any]] = []

    def get(_url: str, **kwargs: Any) -> FakeResponse:
        calls.append(kwargs)
        return FakeResponse(200, [{"date": "2025-09-27", "revenue": 1.0}])

    data = FmpStableClient("test-fmp-key", http_get=get).financial_data(
        "AAPL", period="annual", limit=1
    )

    assert set(data) == {"income_statement", "balance_sheet", "cash_flow", "ratios", "key_metrics"}
    assert all(frame.loc[0, "year"] == 2025 for frame in data.values())
    assert {call["params"]["apikey"] for call in calls} == {"test-fmp-key"}


def test_stable_client_reports_http_failure_without_response_content() -> None:
    def get(_url: str, **_kwargs: Any) -> FakeResponse:
        return FakeResponse(403, {"message": "apikey=test-fmp-key"})

    with pytest.raises(FinRobotCompatibilityError) as error:
        FmpStableClient("test-fmp-key", http_get=get).financial_data(
            "AAPL", period="annual", limit=1
        )

    assert str(error.value) == "FMP stable income-statement returned HTTP 403"
