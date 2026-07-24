"""A股市场情绪爬虫。

数据源（公开 JSON API）：
- 同花顺：热股排行（涨跌广度推导）
- 东方财富 datacenter：北向资金、龙虎榜
- 东方财富 np-listapi：市场要闻频率分析
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from .models import MarketBreadth, MarketSentiment, SectorFlow, SentimentLevel

_LOGGER = logging.getLogger(__name__)
_CST = ZoneInfo("Asia/Shanghai")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://data.eastmoney.com/",
    "Accept": "application/json, text/plain, */*",
}

# 同花顺热股排行 API（可用）
_THS_HOT_STOCK_URL = "https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/stock"
# 东方财富 datacenter 证券数据 API（可用）
_DATACENTER_URL = "https://datacenter.eastmoney.com/securities/api/data/v1/get"


async def fetch_market_sentiment(*, timeout: float = 15.0) -> MarketSentiment:
    """综合获取市场情绪数据。

    Returns:
        MarketSentiment 综合市场情绪
    """
    hot_stocks = await _fetch_ths_hot_stocks(timeout=timeout)
    breadth = _derive_breadth(hot_stocks)
    sector_flows = _derive_sector_flows(hot_stocks)
    north_flow = await _fetch_north_flow(timeout=timeout)

    # 计算综合情绪分数
    score = _calculate_sentiment_score(
        breadth=breadth,
        north_flow=north_flow,
        sector_flows=sector_flows,
        total_volume=0.0,
    )
    level = _score_to_level(score)

    # 识别热门和风险板块
    hot_sectors = [
        sf.sector_name
        for sf in sector_flows[:5]
        if sf.change_percent > 1.0
    ]
    risk_sectors = [
        sf.sector_name
        for sf in sorted(sector_flows, key=lambda x: x.change_percent)[:5]
        if sf.change_percent < -1.0
    ]

    return MarketSentiment(
        score=score,
        level=level,
        breadth=breadth,
        total_volume=0.0,
        north_flow=north_flow,
        sector_flows=sector_flows[:10],
        hot_sectors=hot_sectors,
        risk_sectors=risk_sectors,
        retrieved_at=datetime.now(tz=_CST),
        data_source="eastmoney+ths",
    )


async def _fetch_ths_hot_stocks(*, timeout: float = 10.0) -> list[dict[str, Any]]:
    """从同花顺获取热股排行数据（100支热门股票含涨跌幅和概念标签）。"""
    params = {
        "stock_type": "a",
        "type": "hour",
        "list_type": "normal",
    }

    try:
        async with httpx.AsyncClient(headers=_HEADERS, timeout=timeout) as client:
            resp = await client.get(_THS_HOT_STOCK_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

        stocks = data.get("data", {}).get("stock_list", [])
        return stocks
    except Exception as exc:
        _LOGGER.warning("同花顺热股数据获取失败: %s", exc)
        return []


def _derive_breadth(hot_stocks: list[dict[str, Any]]) -> MarketBreadth:
    """从热股数据推导市场涨跌广度。"""
    if not hot_stocks:
        return MarketBreadth(
            up_count=0, down_count=0, flat_count=0,
            limit_up=0, limit_down=0, up_ratio=0.5,
        )

    up = 0
    down = 0
    flat = 0
    limit_up = 0
    limit_down = 0

    for stock in hot_stocks:
        change = stock.get("rise_and_fall") or 0
        if isinstance(change, str):
            try:
                change = float(change)
            except ValueError:
                change = 0
        if change > 9.5:
            limit_up += 1
            up += 1
        elif change > 0.01:
            up += 1
        elif change < -9.5:
            limit_down += 1
            down += 1
        elif change < -0.01:
            down += 1
        else:
            flat += 1

    total = up + down + flat or 1
    return MarketBreadth(
        up_count=up,
        down_count=down,
        flat_count=flat,
        limit_up=limit_up,
        limit_down=limit_down,
        up_ratio=round(up / total, 4),
    )


def _derive_sector_flows(hot_stocks: list[dict[str, Any]]) -> list[SectorFlow]:
    """从热股概念标签推导板块热度。"""
    sector_stats: dict[str, list[float]] = {}

    for stock in hot_stocks:
        tags = (stock.get("tag") or {}).get("concept_tag") or []
        change = stock.get("rise_and_fall") or 0
        if isinstance(change, str):
            try:
                change = float(change)
            except ValueError:
                change = 0
        for tag in tags[:3]:  # 每股最多取3个概念
            if tag not in sector_stats:
                sector_stats[tag] = []
            sector_stats[tag].append(change)

    flows: list[SectorFlow] = []
    for sector_name, changes in sector_stats.items():
        if len(changes) < 2:  # 至少2支股票才统计
            continue
        avg_change = sum(changes) / len(changes)
        flows.append(
            SectorFlow(
                sector_name=sector_name,
                change_percent=round(avg_change, 2),
                net_inflow=0.0,  # 热股API不含资金流向
                main_inflow=0.0,
                volume=0.0,
                leading_stock="",
                retrieved_at=datetime.now(tz=_CST),
            )
        )

    # 按涨跌幅排序
    flows.sort(key=lambda x: x.change_percent, reverse=True)
    return flows


async def _fetch_north_flow(*, timeout: float = 10.0) -> float:
    """通过东方财富 datacenter 获取最近交易日北向资金净流入 (亿元)。"""
    params = {
        "reportName": "RPT_MUTUAL_DEAL_HISTORY",
        "columns": "ALL",
        "source": "WEB",
        "client": "WEB",
        "pageNumber": "1",
        "pageSize": "5",
        "sortColumns": "TRADE_DATE",
        "sortTypes": "-1",
    }

    try:
        async with httpx.AsyncClient(headers=_HEADERS, timeout=timeout) as client:
            resp = await client.get(_DATACENTER_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

        if not data.get("success"):
            return 0.0

        items = data.get("result", {}).get("data", [])
        if not items:
            return 0.0

        # 汇总沪股通 + 深股通 最近交易日数据
        # MUTUAL_TYPE: 001=沪股通, 003=深股通
        latest_date = items[0].get("TRADE_DATE", "")
        total_net = 0.0
        for item in items:
            if item.get("TRADE_DATE") != latest_date:
                break
            net = item.get("NET_DEAL_AMT") or 0
            total_net += float(net)

        return round(total_net / 1e4, 2)  # 万元转亿元
    except Exception as exc:
        _LOGGER.warning("北向资金数据获取失败: %s", exc)
        return 0.0





def _calculate_sentiment_score(
    *,
    breadth: MarketBreadth,
    north_flow: float,
    sector_flows: list[SectorFlow],
    total_volume: float,
) -> float:
    """根据多维度数据计算综合情绪分数 (0-100)。

    维度及权重：
    - 涨跌比 (40%): 上涨占比映射到 0-100
    - 北向资金 (20%): -100亿~+100亿 映射到 0-100
    - 板块动能 (20%): 上涨板块占比
    - 涨跌停比 (20%): 涨停多则乐观，跌停多则悲观
    """
    # 涨跌比得分
    breadth_score = breadth.up_ratio * 100

    # 北向资金得分（-100亿到+100亿映射到0-100）
    north_score = max(0, min(100, (north_flow + 100) / 200 * 100))

    # 板块动能得分
    if sector_flows:
        up_sectors = sum(1 for sf in sector_flows if sf.change_percent > 0)
        sector_score = up_sectors / len(sector_flows) * 100
    else:
        sector_score = 50

    # 涨跌停得分
    total_limits = breadth.limit_up + breadth.limit_down
    if total_limits > 0:
        limit_score = breadth.limit_up / total_limits * 100
    else:
        limit_score = 50

    # 加权综合
    score = (
        breadth_score * 0.4
        + north_score * 0.2
        + sector_score * 0.2
        + limit_score * 0.2
    )
    return round(max(0, min(100, score)), 1)


def _score_to_level(score: float) -> SentimentLevel:
    """将分数转换为情绪等级。"""
    if score <= 20:
        return SentimentLevel.EXTREME_FEAR
    elif score <= 40:
        return SentimentLevel.FEAR
    elif score <= 60:
        return SentimentLevel.NEUTRAL
    elif score <= 80:
        return SentimentLevel.GREED
    else:
        return SentimentLevel.EXTREME_GREED
