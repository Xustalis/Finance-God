"""Opt-in real PandaData regression for public market-fact routes."""

from __future__ import annotations

import os

import pytest
from starlette.testclient import TestClient

from app.config import settings  # Loads repository-local development settings.
from app.main import app

_ = settings


pytestmark = pytest.mark.skipif(
    not (
        os.environ.get("RUN_PANDADATA_LIVE_SMOKE") == "1"
        and os.environ.get("PANDA_DATA_USERNAME")
        and os.environ.get("PANDA_DATA_PASSWORD")
    ),
    reason="set RUN_PANDADATA_LIVE_SMOKE=1 with credentials for live regression",
)


def test_live_information_fact_route_serializes_non_finite_upstream_values() -> None:
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            "/api/market/information-facts"
            "?symbol=000001.SZ&start_quarter=2025q1&end_quarter=2026q2&limit=1"
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["fact_kind"] == "company_disclosure"
    assert payload["facts"]
    assert payload["facts"][0]["source"]["endpoint"] == "get_fina_reports"
