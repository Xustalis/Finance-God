"""市场环境 Agent - 分析市场情绪、事件与数据质量"""

from app.agents.base import AgentPlugin, AgentInput, AgentOutput


def _normalize(value: float, low: float, high: float) -> float:
    """将 value 线性归一化到 [0, 1] 区间"""
    if high == low:
        return 0.5
    return max(0.0, min(1.0, (value - low) / (high - low)))


# 当 context 中无市场数据时使用的模拟默认值
_MOCK_MARKET_DATA: dict[str, dict] = {
    "a_shares": {"recent_return": 0.02, "volatility": 0.18, "volume_change": 0.05, "breadth_ratio": 1.1},
    "us_stocks": {"recent_return": 0.03, "volatility": 0.15, "volume_change": 0.08, "breadth_ratio": 1.2},
    "hk_stocks": {"recent_return": -0.01, "volatility": 0.20, "volume_change": -0.03, "breadth_ratio": 0.9},
}

_MARKET_LABELS: dict[str, str] = {
    "a_shares": "A股",
    "us_stocks": "美股",
    "hk_stocks": "港股",
}


class MarketAgent(AgentPlugin):
    """分析 A 股、美股、港股的市场情绪，生成事件摘要并评估数据质量"""

    @property
    def name(self) -> str:
        return "market_agent"

    @property
    def capabilities(self) -> list[str]:
        return ["market_analysis", "sentiment_scoring", "event_detection"]

    async def execute(self, input: AgentInput) -> AgentOutput:
        try:
            market_data = input.context.get("market_data", {})
            events = input.context.get("market_events", [])

            markets: dict[str, dict] = {}
            data_quality: dict[str, dict] = {}
            sentiment_scores: list[float] = []

            for market_key in ("a_shares", "us_stocks", "hk_stocks"):
                raw = market_data.get(market_key)
                if raw:
                    scored = self._score_market(raw)
                    data_quality[market_key] = {"status": "fresh", "source": "context"}
                else:
                    scored = self._score_market(_MOCK_MARKET_DATA[market_key])
                    data_quality[market_key] = {"status": "mock", "source": "default"}

                markets[market_key] = {
                    "name": _MARKET_LABELS[market_key],
                    "sentiment": scored["sentiment"],
                    "momentum": scored["momentum"],
                    "volatility": scored["volatility"],
                    "trend": scored["trend"],
                }
                sentiment_scores.append(scored["sentiment"])

            overall_sentiment = (
                sum(sentiment_scores) / len(sentiment_scores) if sentiment_scores else 0.5
            )

            fresh_count = sum(1 for v in data_quality.values() if v["status"] == "fresh")
            if fresh_count == 3:
                usable_status = "usable"
            elif fresh_count >= 1:
                usable_status = "stale"
            else:
                usable_status = "insufficient"

            events_summary = self._summarize_events(events)

            return AgentOutput(
                agent_name=self.name,
                status="success",
                data={
                    "markets": markets,
                    "overall_sentiment": round(overall_sentiment, 4),
                    "events_summary": events_summary,
                    "data_quality": data_quality,
                    "usable_status": usable_status,
                },
                trace={
                    "markets_analyzed": list(markets.keys()),
                    "data_sources": {k: v["source"] for k, v in data_quality.items()},
                },
            )
        except Exception as e:
            return AgentOutput(
                agent_name=self.name,
                status="failed",
                error=str(e),
            )

    def _score_market(self, data: dict) -> dict:
        """基于动量、波动率、成交量趋势、广度计算市场情绪评分（0-1）"""
        momentum = _normalize(float(data.get("recent_return", 0.0)), -0.05, 0.05)
        volatility_raw = float(data.get("volatility", 0.2))
        vol_score = 1.0 - _normalize(volatility_raw, 0.05, 0.40)
        volume_trend = _normalize(float(data.get("volume_change", 0.0)), -0.20, 0.20)
        breadth = _normalize(float(data.get("breadth_ratio", 1.0)), 0.50, 1.50)

        sentiment = (
            0.30 * momentum
            + 0.25 * vol_score
            + 0.20 * volume_trend
            + 0.25 * breadth
        )
        sentiment = max(0.0, min(1.0, sentiment))

        if sentiment > 0.6:
            trend = "bullish"
        elif sentiment < 0.4:
            trend = "bearish"
        else:
            trend = "neutral"

        return {
            "sentiment": round(sentiment, 4),
            "momentum": round(momentum, 4),
            "volatility": round(volatility_raw, 4),
            "trend": trend,
        }

    def _summarize_events(self, events: list) -> list[dict]:
        """将原始事件列表整理为结构化摘要"""
        if not events:
            return []

        summary: list[dict] = []
        for evt in events[:20]:
            summary.append({
                "title": evt.get("title", evt.get("event", "未知事件")),
                "market": evt.get("market", "global"),
                "impact": evt.get("impact", "neutral"),
                "timestamp": evt.get("timestamp", evt.get("date")),
            })
        return summary

    async def health_check(self) -> dict:
        return {"status": "healthy"}


def register():
    from app.plugins.registry import agent_registry
    agent_registry.register("market_agent", MarketAgent)
