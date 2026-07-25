"""A股行业资讯与市场情绪 API 路由。"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from finance_god.crawler.models import MarketNewsEnvelope, MarketNewsItem
from finance_god.crawler.news_crawler import news_item_id
from finance_god.crawler.service import get_crawler_service

_CST = ZoneInfo("Asia/Shanghai")
_LOGGER = logging.getLogger(__name__)


def _parse_limit(request: Request, *, default: int = 20) -> int:
    raw = request.query_params.get("limit", str(default))
    try:
        limit = int(raw)
    except ValueError as exc:
        raise ValueError("limit must be an integer between 1 and 50") from exc
    if not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")
    return limit


async def get_news(request: Request) -> JSONResponse:
    """获取行业资讯。

    Query params:
        sector: 行业板块（可选）
        limit: 返回条数（默认 20，最大 50）
        refresh: 是否强制刷新（0/1）
    """
    sector = request.query_params.get("sector", "")
    force_refresh = request.query_params.get("refresh", "0") == "1"

    try:
        limit = _parse_limit(request)
        news = await get_crawler_service().get_news(
            sector=sector, limit=limit, force_refresh=force_refresh
        )
        return JSONResponse(
            {
                "success": True,
                "count": len(news),
                "data": [item.model_dump(mode="json") for item in news],
            }
        )
    except ValueError as exc:
        return JSONResponse(
            {
                "success": False,
                "error": {"code": "INVALID_LIMIT", "message": str(exc)},
                "data": [],
            },
            status_code=422,
        )
    except Exception as exc:
        return JSONResponse(
            {
                "success": False,
                "error": {
                    "code": "MARKET_NEWS_UNAVAILABLE",
                    "message": str(exc),
                },
                "data": [],
            },
            status_code=502,
        )


async def get_market_news(request: Request) -> JSONResponse:
    """Return real public news through the normalized market boundary."""

    requested_at = datetime.now(tz=_CST)
    try:
        limit = _parse_limit(request)
        snapshot = await get_crawler_service().get_news_snapshot(
            sector=request.query_params.get("sector", ""),
            limit=limit,
            force_refresh=request.query_params.get("refresh", "0") == "1",
        )
        items: list[MarketNewsItem] = []
        dropped_count = 0
        for item in snapshot.items:
            try:
                payload = item.model_dump()
                payload["id"] = news_item_id(url=item.url, title=item.title)
                items.append(MarketNewsItem.model_validate(payload))
            except ValidationError:
                dropped_count += 1
        if not items:
            raise RuntimeError("public-news sources returned no usable items")
        warnings = list(snapshot.warnings)
        if dropped_count:
            warnings.append(
                f"{dropped_count} 条缺少有效来源链接或发布时间的资讯已被剔除。"
            )
        envelope = MarketNewsEnvelope(
            requested_at=requested_at,
            fetched_at=snapshot.fetched_at,
            freshness=snapshot.freshness,
            items=items,
            warnings=warnings,
        )
        return JSONResponse(envelope.model_dump(mode="json"))
    except ValueError as exc:
        return JSONResponse(
            {"error": {"code": "INVALID_LIMIT", "message": str(exc)}},
            status_code=422,
        )
    except Exception as exc:
        _LOGGER.warning("公开资讯接口不可用: %s", exc)
        return JSONResponse(
            {
                "error": {
                    "code": "MARKET_NEWS_UNAVAILABLE",
                    "message": "公开资讯源暂时不可用，请稍后重试。",
                }
            },
            status_code=502,
        )


async def get_sentiment(request: Request) -> JSONResponse:
    """获取市场情绪指标。

    Query params:
        refresh: 是否强制刷新（0/1）
    """
    force_refresh = request.query_params.get("refresh", "0") == "1"

    try:
        sentiment = await get_crawler_service().get_sentiment(
            force_refresh=force_refresh
        )
        return JSONResponse(
            {
                "success": True,
                "data": sentiment.model_dump(mode="json"),
            }
        )
    except Exception as exc:
        return JSONResponse(
            {"success": False, "error": str(exc), "data": None},
            status_code=502,
        )


async def get_full_report(request: Request) -> JSONResponse:
    """获取完整市场报告（资讯 + 情绪）。

    Query params:
        sector: 行业板块（可选）
        limit: 资讯条数（默认 20）
        refresh: 是否强制刷新（0/1）
    """
    sector = request.query_params.get("sector", "")
    force_refresh = request.query_params.get("refresh", "0") == "1"

    try:
        limit = _parse_limit(request)
        result = await get_crawler_service().get_full_report(
            sector=sector, news_limit=limit, force_refresh=force_refresh
        )
        return JSONResponse(
            result.model_dump(mode="json"),
            status_code=200 if result.success else 502,
        )
    except ValueError as exc:
        return JSONResponse(
            {
                "success": False,
                "error": {"code": "INVALID_LIMIT", "message": str(exc)},
            },
            status_code=422,
        )
    except Exception as exc:
        return JSONResponse(
            {"success": False, "error": str(exc)},
            status_code=500,
        )


def create_crawler_routes() -> list[Route]:
    """创建爬虫模块路由列表。"""
    return [
        Route("/market/news", endpoint=get_market_news, methods=["GET"]),
        Route("/crawler/news", endpoint=get_news, methods=["GET"]),
        Route("/crawler/sentiment", endpoint=get_sentiment, methods=["GET"]),
        Route("/crawler/report", endpoint=get_full_report, methods=["GET"]),
    ]
