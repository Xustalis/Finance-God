"""Observation sources for the continuous learning loop.

Two sources are provided:

* :class:`MarketObservationSource` reads recent A-share bars through the
  Finance-God market-data boundary (PandaData).  It is read-only and never
  fabricates values: when data is missing, stale, or conflicted it emits an
  explicit ``degraded`` observation so the failure becomes a learnable signal
  rather than a silent gap.
* :class:`BacktestObservationSource` rotates through the strict past-only
  packs in ``artifacts/backtest`` and carries each case's realized outcome so
  the loop can score predictions deterministically.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Protocol

from .backtest import WalkForwardBacktester
from .contracts import (
    _LESSON_TOPIC_BACKTEST,
    _LESSON_TOPIC_MARKET,
    _LESSON_TOPIC_STRATEGY,
    Observation,
    RealizedOutcome,
    VerifiedResult,
)


class MarketBarReader(Protocol):
    """Structural port over the read-only market-data bar fetch."""

    def read_bars(self, symbol: str, *, limit: int) -> object:
        ...


class MarketObservationSource:
    """Emit evidence-shaped A-share market observations from PandaData."""

    topic = _LESSON_TOPIC_MARKET

    def __init__(
        self,
        reader: MarketBarReader,
        *,
        symbols: tuple[str, ...],
        bar_limit: int,
    ) -> None:
        self._reader = reader
        self._symbols = symbols
        self._bar_limit = bar_limit

    async def observe(self, cycle: int) -> list[Observation]:
        del cycle
        observations: list[Observation] = []
        for symbol in self._symbols:
            observations.append(
                await asyncio.to_thread(self._observe_symbol, symbol)
            )
        return observations

    def _observe_symbol(self, symbol: str) -> Observation:
        try:
            result = self._reader.read_bars(symbol, limit=self._bar_limit)
        except Exception as error:  # noqa: BLE001 - degraded signal is intentional
            return Observation(
                identifier=_stable_identifier(
                    "MKT-ERR", symbol, type(error).__name__
                ),
                source=f"PandaData:{symbol}",
                excerpt=(
                    f"{symbol} 行情读取失败（{type(error).__name__}）；"
                    "本轮无法学习该标的的真实价格结构。"
                ),
                topic=self.topic,
                degraded=True,
            )
        bars = tuple(getattr(result, "bars", ()) or ())
        quality, degraded = _quality_status(result)
        if not bars:
            message = getattr(result, "error_message", None) or "无归一化 K 线"
            return Observation(
                identifier=_stable_identifier(
                    "MKT-EMPTY", symbol, message, quality
                ),
                source=f"PandaData:{symbol}",
                excerpt=f"{symbol} 无可用行情：{message}（质量={quality}）。",
                topic=self.topic,
                degraded=True,
            )
        summary = self._summarize(symbol, bars, quality)
        return Observation(
            identifier=_stable_identifier("MKT", symbol, summary),
            source=f"PandaData:{symbol}",
            excerpt=summary,
            topic=self.topic,
            degraded=degraded,
            verified_result=(
                None
                if degraded
                else VerifiedResult(
                    statement=summary,
                    validation_method="pandadata_quality_gate_v1",
                    tags=["market_observation", symbol],
                    metadata={"symbol": symbol},
                )
            ),
            metadata={"symbol": symbol},
        )

    @staticmethod
    def _summarize(symbol: str, bars: tuple[object, ...], quality: str) -> str:
        first = bars[0]
        last = bars[-1]
        first_close = float(getattr(first, "close"))
        last_close = float(getattr(last, "close"))
        change = (
            (last_close - first_close) / first_close * 100.0
            if first_close
            else 0.0
        )
        highs = [float(getattr(bar, "high")) for bar in bars]
        lows = [float(getattr(bar, "low")) for bar in bars]
        freshness = getattr(last, "freshness", "unknown")
        provider_time = getattr(last, "provider_time", "unknown")
        return (
            f"{symbol} 最近 {len(bars)} 根K线：收盘 {first_close:.4f}→{last_close:.4f}"
            f"（{change:+.2f}%），区间高 {max(highs):.4f} / 低 {min(lows):.4f}，"
            f"最新收盘 {last_close:.4f}，数据时效={freshness}，"
            f"上游时间={provider_time}，质量={quality}。"
        )


class RollingPredictionObservationSource:
    """Build a past-only prediction case from current PandaData history."""

    topic = _LESSON_TOPIC_BACKTEST

    def __init__(
        self,
        reader: MarketBarReader,
        *,
        symbols: tuple[str, ...],
        bar_limit: int,
    ) -> None:
        self._reader = reader
        self._symbols = symbols
        self._bar_limit = bar_limit

    async def observe(self, cycle: int) -> list[Observation]:
        symbol = self._symbols[(cycle // len(self._symbols)) % len(self._symbols)]
        observation = await asyncio.to_thread(self._observe_symbol, symbol)
        return [observation]

    def _observe_symbol(self, symbol: str) -> Observation:
        try:
            result = self._reader.read_bars(symbol, limit=self._bar_limit)
        except Exception as error:  # noqa: BLE001 - explicit degraded observation
            return _degraded_observation(
                prefix="PRED-ERR",
                symbol=symbol,
                topic=self.topic,
                message=f"预测回测行情读取失败（{type(error).__name__}）。",
            )
        bars = tuple(getattr(result, "bars", ()) or ())
        quality, degraded = _quality_status(result)
        frequency = str(getattr(result, "frequency", "unknown"))
        if degraded or frequency != "日频" or len(bars) < 40:
            return _degraded_observation(
                prefix="PRED-SKIP",
                symbol=symbol,
                topic=self.topic,
                message=(
                    f"预测回测需要至少40根已通过质量门的日频K线；"
                    f"当前 bars={len(bars)}、frequency={frequency}、quality={quality}。"
                ),
            )

        horizon = max(5, min(20, len(bars) // 5))
        past = bars[:-horizon]
        cutoff = str(getattr(past[-1], "time"))
        horizon_end = str(getattr(bars[-1], "time"))
        first_future_close = float(getattr(past[-1], "close"))
        last_future_close = float(getattr(bars[-1], "close"))
        realized_return = (
            (last_future_close / first_future_close - 1.0) * 100.0
        )
        direction = (
            "UP"
            if realized_return > 1.0
            else "DOWN"
            if realized_return < -1.0
            else "FLAT"
        )
        past_summary = MarketObservationSource._summarize(symbol, past, quality)
        excerpt = (
            f"{symbol} walk-forward 预测案例：只能使用截至 {cutoff} 的数据，"
            f"预测截至 {horizon_end} 的方向。{past_summary}"
            "每个 Agent 必须在摘要首行严格输出 "
            "PREDICTION: UP、PREDICTION: DOWN 或 PREDICTION: FLAT。"
        )
        return Observation(
            identifier=_stable_identifier(
                "PRED", symbol, cutoff, horizon_end, past_summary
            ),
            source=f"PandaData:prediction:{symbol}:{cutoff}:{horizon_end}",
            excerpt=excerpt,
            topic=self.topic,
            realized_outcome=RealizedOutcome(
                direction=direction,
                total_return=realized_return,
                horizon_end=horizon_end,
            ),
            metadata={
                "symbol": symbol,
                "cutoff": cutoff,
                "horizon_end": horizon_end,
                "frequency": frequency,
            },
        )


class StrategyBacktestObservationSource:
    """Run a deterministic cost-aware SMA walk-forward baseline."""

    topic = _LESSON_TOPIC_STRATEGY

    def __init__(
        self,
        reader: MarketBarReader,
        *,
        symbols: tuple[str, ...],
        bar_limit: int,
        transaction_cost_bps: float,
    ) -> None:
        self._reader = reader
        self._symbols = symbols
        self._bar_limit = bar_limit
        self._backtester = WalkForwardBacktester(
            transaction_cost_bps=transaction_cost_bps
        )

    async def observe(self, cycle: int) -> list[Observation]:
        symbol = self._symbols[(cycle // len(self._symbols)) % len(self._symbols)]
        observation = await asyncio.to_thread(self._observe_symbol, symbol)
        return [observation]

    def _observe_symbol(self, symbol: str) -> Observation:
        try:
            result = self._reader.read_bars(symbol, limit=self._bar_limit)
        except Exception as error:  # noqa: BLE001 - explicit degraded observation
            return _degraded_observation(
                prefix="STRAT-ERR",
                symbol=symbol,
                topic=self.topic,
                message=f"策略回测行情读取失败（{type(error).__name__}）。",
            )
        bars = tuple(getattr(result, "bars", ()) or ())
        quality, degraded = _quality_status(result)
        frequency = str(getattr(result, "frequency", "unknown"))
        if degraded or frequency != "日频":
            return _degraded_observation(
                prefix="STRAT-SKIP",
                symbol=symbol,
                topic=self.topic,
                message=(
                    f"策略回测只接受已通过质量门的日频K线；"
                    f"当前 frequency={frequency}、quality={quality}。"
                ),
            )
        try:
            verified = self._backtester.evaluate(symbol=symbol, bars=bars)
        except ValueError as error:
            return _degraded_observation(
                prefix="STRAT-SKIP",
                symbol=symbol,
                topic=self.topic,
                message=str(error),
            )
        return Observation(
            identifier=_stable_identifier("STRAT", verified.statement),
            source=f"PandaData:strategy-backtest:{symbol}",
            excerpt=(
                f"{verified.statement} 请分析该结果的适用区间、失效条件与"
                "进一步验证需求，不得把历史回测表述为收益保证。"
            ),
            topic=self.topic,
            verified_result=verified,
            metadata={"symbol": symbol, "frequency": frequency},
        )


class BacktestObservationSource:
    """Rotate through strict past-only backtest packs with realized truth."""

    topic = _LESSON_TOPIC_BACKTEST

    def __init__(self, backtest_dir: Path) -> None:
        self._dir = backtest_dir
        self._prompts_dir = backtest_dir / "prompts"
        self._index = self._load_index()
        self._ground_truth = self._load_ground_truth()

    def _load_index(self) -> list[dict[str, object]]:
        index_path = self._dir / "index.json"
        if not index_path.exists():
            return []
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, list) else []

    def _load_ground_truth(self) -> dict[str, dict[str, object]]:
        truth_path = self._dir / "ground_truth.json"
        if not truth_path.exists():
            return {}
        payload = json.loads(truth_path.read_text(encoding="utf-8"))
        # Real layout wraps cases under a top-level ``ground_truth`` key.
        if isinstance(payload, dict) and isinstance(payload.get("ground_truth"), dict):
            payload = payload["ground_truth"]
        if isinstance(payload, dict):
            return {str(k): v for k, v in payload.items() if isinstance(v, dict)}
        if isinstance(payload, list):
            return {
                str(item["id"]): item
                for item in payload
                if isinstance(item, dict) and "id" in item
            }
        return {}

    def available(self) -> bool:
        return bool(self._index)

    async def observe(self, cycle: int) -> list[Observation]:
        if not self._index:
            return []
        case = self._index[cycle % len(self._index)]
        case_id = str(case.get("id", f"case-{cycle}"))
        observation = await asyncio.to_thread(self._observe_case, case_id, case)
        return [observation]

    def _observe_case(
        self, case_id: str, case: dict[str, object]
    ) -> Observation:
        prompt_path = self._prompts_dir / f"{case_id}.json"
        asset = str(case.get("asset", case_id))
        cutoff = str(case.get("cutoff", "unknown"))
        horizon_end = str(case.get("horizon_end", "unknown"))
        if prompt_path.exists():
            excerpt = (
                f"回测案例 {case_id}（{asset}）：仅提供截至 {cutoff} 的历史数据，"
                f"预测到 {horizon_end} 的方向与幅度。"
                f"过去数据包：{prompt_path.name}。"
            )
            past_pack = prompt_path.read_text(encoding="utf-8")
            excerpt = (excerpt + " 过去数据摘录：" + past_pack)[:4_000]
        else:
            excerpt = (
                f"回测案例 {case_id}（{asset}）：缺少过去数据包，"
                f"仅依据 {cutoff} 之前的公开信息预测到 {horizon_end}。"
            )
        realized = self._realized(case_id)
        return Observation(
            identifier=_stable_identifier(
                "BT",
                case_id,
                cutoff,
                horizon_end,
                excerpt,
            ),
            source=f"backtest:{case_id}",
            excerpt=excerpt,
            topic=self.topic,
            realized_outcome=realized,
        )

    def _realized(self, case_id: str) -> RealizedOutcome | None:
        truth = self._ground_truth.get(case_id)
        if not truth:
            return None
        direction = truth.get("direction") or truth.get("actual_direction")
        total_return = next(
            (
                truth[key]
                for key in ("pct", "total_return", "return", "actual_return")
                if key in truth and truth[key] is not None
            ),
            None,
        )
        end = truth.get("end")
        horizon_end = (
            str(end["date"])
            if isinstance(end, dict) and "date" in end
            else str(truth.get("horizon_end") or truth.get("horizon") or "unknown")
        )
        if direction is None or total_return is None:
            return None
        try:
            return RealizedOutcome(
                direction=str(direction),
                total_return=float(total_return),
                horizon_end=str(horizon_end),
            )
        except (TypeError, ValueError):
            return None


def _quality_status(result: object) -> tuple[str, bool]:
    quality = getattr(result, "quality", "unknown")
    frozen = getattr(quality, "frozen", None)
    if frozen is not None:
        return ("frozen" if frozen else "accepted"), bool(frozen)
    label = str(quality)
    return label, label.lower() not in {"accept", "accepted", "ok", "released", "pass"}


def _stable_identifier(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"[:64]


def _degraded_observation(
    *,
    prefix: str,
    symbol: str,
    topic: str,
    message: str,
) -> Observation:
    return Observation(
        identifier=_stable_identifier(prefix, symbol, message),
        source=f"PandaData:{symbol}",
        excerpt=message,
        topic=topic,
        degraded=True,
        metadata={"symbol": symbol},
    )


__all__ = [
    "BacktestObservationSource",
    "MarketBarReader",
    "MarketObservationSource",
    "RollingPredictionObservationSource",
    "StrategyBacktestObservationSource",
]
