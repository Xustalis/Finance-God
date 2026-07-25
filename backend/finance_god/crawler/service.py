"""爬虫服务层 - 统一调度行业资讯和市场情绪的采集。"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .models import (
    CrawlerResult,
    IndustryNews,
    MarketSentiment,
    NewsFreshness,
    NewsSnapshot,
)
from .news_crawler import NewsSourcesUnavailable, fetch_industry_news
from .sentiment_crawler import fetch_market_sentiment

_LOGGER = logging.getLogger(__name__)
_CST = ZoneInfo("Asia/Shanghai")

# 缓存有效期
_NEWS_CACHE_TTL = timedelta(minutes=5)
_NEWS_CACHE_FETCH_LIMIT = 50
_SENTIMENT_CACHE_TTL = timedelta(minutes=1)
_SHARED_CRAWLER_SERVICE: CrawlerService | None = None


class CrawlerService:
    """A股行业资讯与市场情绪爬虫服务。

    提供资讯和情绪数据的统一入口，内置简单的内存缓存。
    """

    def __init__(self) -> None:
        self._news_cache: list[IndustryNews] = []
        self._news_cache_time: datetime | None = None
        self._sentiment_cache: MarketSentiment | None = None
        self._sentiment_cache_time: datetime | None = None
        self._lock = asyncio.Lock()

    async def get_news(
        self,
        *,
        sector: str = "",
        limit: int = 30,
        force_refresh: bool = False,
    ) -> list[IndustryNews]:
        """获取行业资讯。

        Args:
            sector: 行业板块（为空则综合）
            limit: 返回条目数
            force_refresh: 是否强制刷新缓存
        """
        snapshot = await self.get_news_snapshot(
            sector=sector,
            limit=limit,
            force_refresh=force_refresh,
        )
        return snapshot.items

    async def get_news_snapshot(
        self,
        *,
        sector: str = "",
        limit: int = 30,
        force_refresh: bool = False,
    ) -> NewsSnapshot:
        """Return public news with truthful cache and freshness metadata."""

        if not 1 <= limit <= _NEWS_CACHE_FETCH_LIMIT:
            raise ValueError(
                f"limit must be between 1 and {_NEWS_CACHE_FETCH_LIMIT}"
            )
        now = datetime.now(tz=_CST)
        if (
            not force_refresh
            and not sector
            and self._news_cache
            and self._news_cache_time
            and (now - self._news_cache_time) < _NEWS_CACHE_TTL
        ):
            return self._snapshot(
                items=self._news_cache[:limit],
                fetched_at=self._news_cache_time,
                requested_at=now,
                cached=True,
            )

        async with self._lock:
            now = datetime.now(tz=_CST)
            if (
                not force_refresh
                and not sector
                and self._news_cache
                and self._news_cache_time
                and (now - self._news_cache_time) < _NEWS_CACHE_TTL
            ):
                return self._snapshot(
                    items=self._news_cache[:limit],
                    fetched_at=self._news_cache_time,
                    requested_at=now,
                    cached=True,
                )

            upstream_limit = _NEWS_CACHE_FETCH_LIMIT if not sector else limit
            try:
                news_list = await fetch_industry_news(
                    sector=sector,
                    limit=upstream_limit,
                )
            except NewsSourcesUnavailable as exc:
                if not sector and self._news_cache and self._news_cache_time:
                    return self._snapshot(
                        items=self._news_cache[:limit],
                        fetched_at=self._news_cache_time,
                        requested_at=now,
                        cached=True,
                        warning=(
                            "实时资讯源刷新失败，当前返回上次成功缓存："
                            f"{type(exc).__name__}"
                        ),
                    )
                raise

            news_list.sort(
                key=lambda x: x.publish_time or datetime.min.replace(tzinfo=_CST),
                reverse=True,
            )

            fetched_at = datetime.now(tz=_CST)
            if not sector:
                self._news_cache = news_list
                self._news_cache_time = fetched_at

            return self._snapshot(
                items=news_list[:limit],
                fetched_at=fetched_at,
                requested_at=now,
                cached=False,
            )

    @staticmethod
    def _snapshot(
        *,
        items: list[IndustryNews],
        fetched_at: datetime,
        requested_at: datetime,
        cached: bool,
        warning: str | None = None,
    ) -> NewsSnapshot:
        age = max(0, int((requested_at - fetched_at).total_seconds()))
        return NewsSnapshot(
            items=items,
            fetched_at=fetched_at,
            freshness=NewsFreshness(
                status=(
                    "fresh"
                    if age < int(_NEWS_CACHE_TTL.total_seconds())
                    else "stale"
                ),
                age_seconds=age,
                ttl_seconds=int(_NEWS_CACHE_TTL.total_seconds()),
                cached=cached,
            ),
            warnings=[warning] if warning else [],
        )

    async def get_sentiment(
        self, *, force_refresh: bool = False
    ) -> MarketSentiment:
        """获取市场情绪指标。

        Args:
            force_refresh: 是否强制刷新缓存
        """
        now = datetime.now(tz=_CST)

        # 检查缓存
        if (
            not force_refresh
            and self._sentiment_cache
            and self._sentiment_cache_time
            and (now - self._sentiment_cache_time) < _SENTIMENT_CACHE_TTL
        ):
            return self._sentiment_cache

        async with self._lock:
            # 双检锁
            if (
                not force_refresh
                and self._sentiment_cache
                and self._sentiment_cache_time
                and (now - self._sentiment_cache_time) < _SENTIMENT_CACHE_TTL
            ):
                return self._sentiment_cache

            sentiment = await fetch_market_sentiment()
            self._sentiment_cache = sentiment
            self._sentiment_cache_time = now
            return sentiment

    async def get_full_report(
        self,
        *,
        sector: str = "",
        news_limit: int = 20,
        force_refresh: bool = False,
    ) -> CrawlerResult:
        """获取完整的市场资讯 + 情绪报告。"""
        errors: list[str] = []

        try:
            news = await self.get_news(
                sector=sector, limit=news_limit, force_refresh=force_refresh
            )
        except Exception as exc:
            _LOGGER.error("资讯获取失败: %s", exc)
            news = []
            errors.append(f"资讯获取失败: {exc}")

        try:
            sentiment = await self.get_sentiment(force_refresh=force_refresh)
        except Exception as exc:
            _LOGGER.error("情绪数据获取失败: %s", exc)
            sentiment = None
            errors.append(f"情绪数据获取失败: {exc}")

        return CrawlerResult(
            success=len(errors) == 0,
            news=news,
            sentiment=sentiment,
            errors=errors,
            retrieved_at=datetime.now(tz=_CST),
        )

    def invalidate_cache(self) -> None:
        """清除所有缓存。"""
        self._news_cache = []
        self._news_cache_time = None
        self._sentiment_cache = None
        self._sentiment_cache_time = None


def get_crawler_service() -> CrawlerService:
    """Return the process-wide crawler cache used by HTTP and workflows."""

    global _SHARED_CRAWLER_SERVICE
    if _SHARED_CRAWLER_SERVICE is None:
        _SHARED_CRAWLER_SERVICE = CrawlerService()
    return _SHARED_CRAWLER_SERVICE
