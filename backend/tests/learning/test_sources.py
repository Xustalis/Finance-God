from __future__ import annotations

import asyncio
import json
from pathlib import Path

from finance_god.learning.sources import (
    BacktestObservationSource,
    MarketObservationSource,
    RollingPredictionObservationSource,
    StrategyBacktestObservationSource,
)

from .support import Reader, bars


def test_market_observation_identifier_changes_with_data_not_cycle() -> None:
    reader = Reader(bars([100.0 + index for index in range(40)]))
    source = MarketObservationSource(
        reader,
        symbols=("510300.SH",),
        bar_limit=40,
    )

    first = asyncio.run(source.observe(1))[0]
    second = asyncio.run(source.observe(99))[0]

    assert first.identifier == second.identifier
    assert first.degraded is False
    assert first.verified_result is not None
    assert (
        first.verified_result.validation_method
        == "pandadata_quality_gate_v1"
    )


def test_prediction_source_hides_holdout_and_keeps_realized_truth_for_scorer() -> None:
    values = [100.0 + index for index in range(50)] + [999.0] * 10
    source = RollingPredictionObservationSource(
        Reader(bars(values)),
        symbols=("510300.SH",),
        bar_limit=60,
    )

    observation = asyncio.run(source.observe(0))[0]

    assert observation.realized_outcome is not None
    assert observation.realized_outcome.direction == "UP"
    assert "999.0000" not in observation.excerpt
    assert "PREDICTION: UP" in observation.excerpt
    assert observation.metadata["symbol"] == "510300.SH"


def test_strategy_source_emits_only_deterministic_verified_result() -> None:
    source = StrategyBacktestObservationSource(
        Reader(bars([100.0 + index * 0.5 for index in range(80)])),
        symbols=("510300.SH",),
        bar_limit=80,
        transaction_cost_bps=10,
    )

    observation = asyncio.run(source.observe(0))[0]

    assert observation.degraded is False
    assert observation.verified_result is not None
    assert observation.verified_result.validation_method == "walk_forward_sma_v1"
    assert "不得把历史回测表述为收益保证" in observation.excerpt


def test_static_backtest_identifier_changes_with_case_not_cycle(
    tmp_path: Path,
) -> None:
    (tmp_path / "prompts").mkdir()
    (tmp_path / "index.json").write_text(
        json.dumps(
            [
                {
                    "id": "case-1",
                    "asset": "BTC",
                    "cutoff": "2024-01-01",
                    "horizon_end": "2024-02-01",
                }
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "prompts" / "case-1.json").write_text(
        '{"prices": [1, 2, 3]}',
        encoding="utf-8",
    )
    (tmp_path / "ground_truth.json").write_text(
        json.dumps(
            {
                "ground_truth": {
                    "case-1": {
                        "direction": "FLAT",
                        "pct": 0,
                        "horizon_end": "2024-02-01",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    source = BacktestObservationSource(tmp_path)

    first = asyncio.run(source.observe(0))[0]
    repeated = asyncio.run(source.observe(99))[0]

    assert first.identifier == repeated.identifier
    assert first.realized_outcome is not None
    assert first.realized_outcome.total_return == 0
