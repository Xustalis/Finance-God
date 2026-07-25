from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from finance_god.api import crawler_routes
from finance_god.crawler.models import IndustryNews
from finance_god.crawler.news_crawler import (
    NewsSourcesUnavailable,
    fetch_industry_news,
    news_item_id,
)
from finance_god.crawler.service import CrawlerService

_CST = ZoneInfo("Asia/Shanghai")


def _news(index: int) -> IndustryNews:
    return IndustryNews(
        title=f"公开资讯 {index}",
        summary="来自公开接口的摘要",
        source="东方财富/测试媒体",
        url=f"https://finance.example.test/news/{index}",
        publish_time=datetime(2026, 7, 25, 9, index % 60, tzinfo=_CST),
        sector="综合",
        tags=["测试媒体"],
    )


@pytest.mark.asyncio
async def test_crawler_uses_normalized_url_and_title_for_deduplication() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "getNewsByColumns" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "list": [
                            {
                                "title": "  同一 条 资讯 ",
                                "summary": "A",
                                "mediaName": "测试媒体",
                                "url": (
                                    "HTTPS://EXAMPLE.TEST/news/1/"
                                    "?utm_source=feed&b=2&a=1#fragment"
                                ),
                                "showTime": "2026-07-25 09:00:00",
                            },
                            {
                                "title": "同一 条 资讯",
                                "summary": "B",
                                "mediaName": "测试媒体",
                                "url": "https://example.test/news/1?a=1&b=2",
                                "showTime": "2026-07-25 09:00:00",
                            },
                        ]
                    }
                },
            )
        return httpx.Response(200, json={"data": []})

    result = await fetch_industry_news(
        limit=10,
        transport=httpx.MockTransport(handler),
    )

    assert len(result) == 1
    assert result[0].source == "东方财富/测试媒体"


def test_news_item_id_uses_normalized_url_and_title() -> None:
    first = news_item_id(
        url=(
            "HTTPS://EXAMPLE.TEST/news/1/"
            "?utm_source=feed&b=2&a=1#fragment"
        ),
        title="  同一 条 资讯 ",
    )
    second = news_item_id(
        url="https://example.test/news/1?a=1&b=2",
        title="同一 条 资讯",
    )

    assert first == second
    assert len(first) == 64
    assert set(first) <= set("0123456789abcdef")


@pytest.mark.asyncio
async def test_crawler_raises_when_every_public_source_fails() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(503, request=request)
    )

    with pytest.raises(NewsSourcesUnavailable, match="all public-news sources failed"):
        await fetch_industry_news(limit=5, transport=transport)


def test_first_small_request_does_not_truncate_shared_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    async def fake_fetch(*, sector: str, limit: int) -> list[IndustryNews]:
        assert sector == ""
        calls.append(limit)
        return [_news(index) for index in range(limit)]

    monkeypatch.setattr(
        "finance_god.crawler.service.fetch_industry_news",
        fake_fetch,
    )
    service = CrawlerService()

    first = asyncio.run(service.get_news(limit=2))
    second = asyncio.run(service.get_news(limit=20))

    assert len(first) == 2
    assert len(second) == 20
    assert calls == [50]


def test_refresh_failure_serves_explicitly_stale_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_fetch(*, sector: str, limit: int) -> list[IndustryNews]:
        raise NewsSourcesUnavailable("upstream unavailable")

    monkeypatch.setattr(
        "finance_god.crawler.service.fetch_industry_news",
        fail_fetch,
    )
    service = CrawlerService()
    service._news_cache = [_news(1)]
    service._news_cache_time = datetime.now(tz=_CST) - timedelta(minutes=10)

    snapshot = asyncio.run(service.get_news_snapshot(limit=5))

    assert snapshot.items
    assert snapshot.freshness.status == "stale"
    assert snapshot.freshness.cached is True
    assert snapshot.warnings


def test_market_news_route_returns_typed_real_data_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(*, sector: str, limit: int) -> list[IndustryNews]:
        return [_news(index) for index in range(limit)]

    monkeypatch.setattr(
        "finance_god.crawler.service.fetch_industry_news",
        fake_fetch,
    )
    service = CrawlerService()
    monkeypatch.setattr(crawler_routes, "get_crawler_service", lambda: service)
    app = Starlette(routes=crawler_routes.create_crawler_routes())

    with TestClient(app) as client:
        response = client.get("/market/news?limit=3")
        cached = client.get("/market/news?limit=2")

    assert response.status_code == 200
    assert response.json() == {
        **{
            key: response.json()[key]
            for key in ("requested_at", "fetched_at", "freshness", "items")
        },
        "provider": "Finance-God crawler",
        "data_mode": "real",
        "trade_eligible": False,
        "warnings": [],
    }
    assert len(response.json()["items"]) == 3
    assert len(response.json()["items"][0]["id"]) == 64
    assert response.json()["items"][0]["publish_time"]
    assert response.json()["items"][0]["source"]
    assert response.json()["items"][0]["url"]
    assert cached.json()["freshness"]["cached"] is True


@pytest.mark.parametrize("limit", ["0", "51", "invalid"])
def test_market_news_route_rejects_invalid_limit(
    limit: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = CrawlerService()
    monkeypatch.setattr(crawler_routes, "get_crawler_service", lambda: service)
    app = Starlette(routes=crawler_routes.create_crawler_routes())

    with TestClient(app) as client:
        response = client.get(f"/market/news?limit={limit}")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_LIMIT"


def test_market_news_route_returns_stable_502_without_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_fetch(*, sector: str, limit: int) -> list[IndustryNews]:
        raise NewsSourcesUnavailable("credentials and network detail")

    monkeypatch.setattr(
        "finance_god.crawler.service.fetch_industry_news",
        fail_fetch,
    )
    service = CrawlerService()
    monkeypatch.setattr(crawler_routes, "get_crawler_service", lambda: service)
    app = Starlette(routes=crawler_routes.create_crawler_routes())

    with TestClient(app) as client:
        response = client.get("/market/news?limit=5")

    assert response.status_code == 502
    assert response.json() == {
        "error": {
            "code": "MARKET_NEWS_UNAVAILABLE",
            "message": "公开资讯源暂时不可用，请稍后重试。",
        }
    }
