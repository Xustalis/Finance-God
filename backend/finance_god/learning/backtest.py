"""Small deterministic walk-forward backtest used by the learning worker."""

from __future__ import annotations

import math
from statistics import fmean, pstdev

from .contracts import VerifiedResult

_PARAMETER_CANDIDATES = ((3, 10), (5, 20), (10, 30))
_TRADING_DAYS = 252


class WalkForwardBacktester:
    """Select an SMA pair in-sample and score it once on held-out bars."""

    def __init__(self, *, transaction_cost_bps: float) -> None:
        self._cost_rate = transaction_cost_bps / 10_000.0

    def evaluate(self, *, symbol: str, bars: tuple[object, ...]) -> VerifiedResult:
        closes = tuple(float(getattr(bar, "close")) for bar in bars)
        if len(closes) < 40 or any(value <= 0 for value in closes):
            raise ValueError("walk-forward backtest requires at least 40 positive closes")

        split = int(len(closes) * 0.7)
        candidates = [
            pair for pair in _PARAMETER_CANDIDATES if pair[1] < split - 1
        ]
        if not candidates:
            raise ValueError("not enough in-sample bars for strategy candidates")

        selected = max(
            candidates,
            key=lambda pair: self._metrics(
                closes,
                fast=pair[0],
                slow=pair[1],
                start=pair[1] - 1,
                stop=split - 1,
            )["sharpe"],
        )
        metrics = self._metrics(
            closes,
            fast=selected[0],
            slow=selected[1],
            start=max(split - 1, selected[1] - 1),
            stop=len(closes) - 1,
        )
        benchmark = (closes[-1] / closes[split - 1] - 1.0) * 100.0
        start_time = str(getattr(bars[split - 1], "time", split - 1))
        end_time = str(getattr(bars[-1], "time", len(bars) - 1))
        statement = (
            f"{symbol} SMA({selected[0]},{selected[1]}) 仅在前70%样本选参，"
            f"后30%样本 {start_time}→{end_time} 含成本收益"
            f" {metrics['total_return']:+.2f}%、Sharpe {metrics['sharpe']:.2f}、"
            f"最大回撤 {metrics['max_drawdown']:.2f}%、换仓 {metrics['trades']} 次；"
            f"同期买入持有 {benchmark:+.2f}%。"
        )
        return VerifiedResult(
            statement=statement,
            validation_method="walk_forward_sma_v1",
            tags=["strategy", "walk_forward", symbol],
            metadata={
                "symbol": symbol,
                "fast_window": selected[0],
                "slow_window": selected[1],
                "test_start": start_time,
                "test_end": end_time,
                "transaction_cost_bps": self._cost_rate * 10_000.0,
                "benchmark_return": benchmark,
                **metrics,
            },
        )

    def _metrics(
        self,
        closes: tuple[float, ...],
        *,
        fast: int,
        slow: int,
        start: int,
        stop: int,
    ) -> dict[str, float | int]:
        position = 0
        returns: list[float] = []
        equity = 1.0
        peak = 1.0
        max_drawdown = 0.0
        trades = 0
        for index in range(max(start, slow - 1), stop):
            fast_average = fmean(closes[index - fast + 1 : index + 1])
            slow_average = fmean(closes[index - slow + 1 : index + 1])
            next_position = 1 if fast_average > slow_average else 0
            turnover = abs(next_position - position)
            trades += turnover
            period_return = (
                next_position * (closes[index + 1] / closes[index] - 1.0)
                - turnover * self._cost_rate
            )
            returns.append(period_return)
            equity *= 1.0 + period_return
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, (peak - equity) / peak)
            position = next_position

        if not returns:
            raise ValueError("walk-forward window produced no returns")
        volatility = pstdev(returns)
        sharpe = (
            fmean(returns) / volatility * math.sqrt(_TRADING_DAYS)
            if volatility > 0
            else 0.0
        )
        return {
            "total_return": (equity - 1.0) * 100.0,
            "sharpe": sharpe,
            "max_drawdown": max_drawdown * 100.0,
            "trades": trades,
            "observations": len(returns),
        }


__all__ = ["WalkForwardBacktester"]
