"""A股行业资讯与市场情绪 API 路由。"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from finance_god.crawler.service import get_crawler_service


async def get_news(request: Request) -> JSONResponse:
    """获取行业资讯。

    Query params:
        sector: 行业板块（可选）
        limit: 返回条数（默认 20，最大 50）
        refresh: 是否强制刷新（0/1）
    """
    sector = request.query_params.get("sector", "")
    limit = min(int(request.query_params.get("limit", "20")), 50)
    force_refresh = request.query_params.get("refresh", "0") == "1"

    try:
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
    except Exception as exc:
        return JSONResponse(
            {"success": False, "error": str(exc), "data": []},
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
    limit = min(int(request.query_params.get("limit", "20")), 50)
    force_refresh = request.query_params.get("refresh", "0") == "1"

    try:
        result = await get_crawler_service().get_full_report(
            sector=sector, news_limit=limit, force_refresh=force_refresh
        )
        return JSONResponse(
            result.model_dump(mode="json"),
            status_code=200 if result.success else 502,
        )
    except Exception as exc:
        return JSONResponse(
            {"success": False, "error": str(exc)},
            status_code=500,
        )


def create_crawler_routes() -> list[Route]:
    """创建爬虫模块路由列表。"""
    return [
        Route("/crawler/news", endpoint=get_news, methods=["GET"]),
        Route("/crawler/sentiment", endpoint=get_sentiment, methods=["GET"]),
        Route("/crawler/report", endpoint=get_full_report, methods=["GET"]),
    ]
