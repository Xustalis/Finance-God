"""爬虫模块数据模型定义。"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class SentimentLevel(str, Enum):
    """市场情绪等级。"""

    EXTREME_FEAR = "extreme_fear"  # 极度恐慌
    FEAR = "fear"  # 恐慌
    NEUTRAL = "neutral"  # 中性
    GREED = "greed"  # 贪婪
    EXTREME_GREED = "extreme_greed"  # 极度贪婪


class IndustryNews(BaseModel):
    """行业资讯条目。"""

    model_config = ConfigDict(frozen=True)

    title: str = Field(description="资讯标题")
    summary: str = Field(default="", description="摘要内容")
    source: str = Field(description="来源（如东方财富、新浪财经）")
    url: str = Field(description="原文链接")
    publish_time: datetime | None = Field(default=None, description="发布时间")
    sector: str = Field(default="", description="所属行业板块")
    tags: list[str] = Field(default_factory=list, description="标签")


class SectorFlow(BaseModel):
    """板块资金流向。"""

    model_config = ConfigDict(frozen=True)

    sector_name: str = Field(description="板块名称")
    change_percent: float = Field(description="涨跌幅 (%)")
    net_inflow: float = Field(description="净流入金额 (亿元)")
    main_inflow: float = Field(default=0.0, description="主力净流入 (亿元)")
    volume: float = Field(default=0.0, description="成交额 (亿元)")
    leading_stock: str = Field(default="", description="领涨股")
    retrieved_at: datetime = Field(default_factory=datetime.now)


class MarketBreadth(BaseModel):
    """市场涨跌广度。"""

    model_config = ConfigDict(frozen=True)

    up_count: int = Field(description="上涨家数")
    down_count: int = Field(description="下跌家数")
    flat_count: int = Field(description="平盘家数")
    limit_up: int = Field(default=0, description="涨停家数")
    limit_down: int = Field(default=0, description="跌停家数")
    up_ratio: float = Field(description="上涨占比")


class MarketSentiment(BaseModel):
    """综合市场情绪指标。"""

    model_config = ConfigDict(frozen=True)

    score: float = Field(ge=0, le=100, description="情绪评分 0-100")
    level: SentimentLevel = Field(description="情绪等级")
    breadth: MarketBreadth = Field(description="涨跌广度")
    turnover_rate: float = Field(default=0.0, description="市场换手率 (%)")
    total_volume: float = Field(default=0.0, description="两市总成交额 (亿元)")
    north_flow: float = Field(default=0.0, description="北向资金净流入 (亿元)")
    sector_flows: list[SectorFlow] = Field(
        default_factory=list, description="板块资金流向 TOP10"
    )
    hot_sectors: list[str] = Field(default_factory=list, description="热门板块")
    risk_sectors: list[str] = Field(default_factory=list, description="风险板块")
    retrieved_at: datetime = Field(default_factory=datetime.now)
    data_source: str = Field(default="eastmoney", description="数据源")


class CrawlerResult(BaseModel):
    """爬虫结果包装。"""

    model_config = ConfigDict(frozen=True)

    success: bool
    news: list[IndustryNews] = Field(default_factory=list)
    sentiment: MarketSentiment | None = None
    errors: list[str] = Field(default_factory=list)
    retrieved_at: datetime = Field(default_factory=datetime.now)
