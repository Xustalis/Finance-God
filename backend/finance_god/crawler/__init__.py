"""A股行业资讯与市场情绪爬虫模块。

数据源：
- 东方财富：行业资讯、板块资金流向、市场情绪指标
- 同花顺：市场情绪指数、涨跌统计
"""

from .models import IndustryNews, MarketSentiment, SectorFlow
from .service import CrawlerService

__all__ = [
    "CrawlerService",
    "IndustryNews",
    "MarketSentiment",
    "SectorFlow",
]
