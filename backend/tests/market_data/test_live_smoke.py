from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv
from finance_god.market_data import (
    DataFrequency,
    PandaDataAdapter,
    ReleaseState,
)
from finance_god.market_data.instruments import DEFAULT_INSTRUMENT_MASTER


def _live_adapter() -> PandaDataAdapter:
    backend_root = Path(__file__).resolve().parents[2]
    load_dotenv(backend_root / ".env", override=False)
    return PandaDataAdapter.from_environment()


@pytest.mark.skipif(
    os.environ.get("RUN_PANDADATA_LIVE_SMOKE") != "1",
    reason="set RUN_PANDADATA_LIVE_SMOKE=1 for the explicit live smoke",
)
def test_live_a_share_quote_requires_a_real_normalized_item() -> None:
    adapter = _live_adapter()
    instrument = DEFAULT_INSTRUMENT_MASTER.resolve("000001.SZ")

    quote = adapter.fetch_snapshot(
        instrument,
        release_state=ReleaseState.RELEASED,
    )

    assert quote.items, quote.diagnostics
    assert quote.items[0].source.provider == "PandaData"
    assert quote.items[0].source.frequency is DataFrequency.SNAPSHOT


@pytest.mark.skipif(
    os.environ.get("RUN_PANDADATA_LIVE_SMOKE") != "1",
    reason="set RUN_PANDADATA_LIVE_SMOKE=1 for the explicit live smoke",
)
def test_live_released_historical_1m_requires_real_rows() -> None:
    adapter = _live_adapter()
    instrument = DEFAULT_INSTRUMENT_MASTER.resolve("000001.SZ")
    bars = adapter.fetch_bars(
        instrument,
        frequency=DataFrequency.MINUTE_1,
        start_date="20260723",
        end_date="20260723",
        limit=5,
        release_state=ReleaseState.RELEASED,
    )

    assert bars.items, bars.diagnostics
    assert bars.items[-1].source.frequency is DataFrequency.MINUTE_1
    assert bars.items[-1].source.endpoint == "get_stock_min"
