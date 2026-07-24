from __future__ import annotations

from finance_god.learning.backtest import WalkForwardBacktester

from .support import bars


def test_walk_forward_selects_parameters_without_held_out_lookahead() -> None:
    training = [100.0 + index * 0.4 for index in range(56)]
    positive_tail = [training[-1] + index * 2.0 for index in range(1, 25)]
    negative_tail = [training[-1] - index * 1.2 for index in range(1, 25)]
    backtester = WalkForwardBacktester(transaction_cost_bps=10)

    positive = backtester.evaluate(
        symbol="510300.SH",
        bars=bars([*training, *positive_tail]),
    )
    negative = backtester.evaluate(
        symbol="510300.SH",
        bars=bars([*training, *negative_tail]),
    )

    assert positive.metadata["fast_window"] == negative.metadata["fast_window"]
    assert positive.metadata["slow_window"] == negative.metadata["slow_window"]
    assert positive.metadata["total_return"] != negative.metadata["total_return"]
    assert positive.validation_method == "walk_forward_sma_v1"


def test_transaction_cost_is_applied_to_held_out_returns() -> None:
    values = [100.0 + (index % 8) * 2.0 for index in range(80)]

    without_cost = WalkForwardBacktester(transaction_cost_bps=0).evaluate(
        symbol="510300.SH",
        bars=bars(values),
    )
    with_cost = WalkForwardBacktester(transaction_cost_bps=20).evaluate(
        symbol="510300.SH",
        bars=bars(values),
    )

    assert with_cost.metadata["total_return"] <= without_cost.metadata["total_return"]
    assert with_cost.metadata["transaction_cost_bps"] == 20
