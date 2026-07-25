from __future__ import annotations

import asyncio
from types import SimpleNamespace

from finance_god.orchestration.crawler_data_provider import CrawlerDataProvider
from research_runtime.models import DataQuery, PandaDataDataset


class _Crawler:
    async def get_sentiment(self):
        return SimpleNamespace(
            score=62,
            level=SimpleNamespace(value="neutral"),
            north_flow=1.5,
            breadth=SimpleNamespace(
                up_ratio=0.55,
                up_count=2800,
                down_count=2100,
                limit_up=45,
                limit_down=8,
            ),
            total_volume=9000,
            data_source="crawler",
            sector_flows=(),
        )


def _query() -> DataQuery:
    return DataQuery(
        identifier="market-sentiment",
        dataset=PandaDataDataset.MARGIN,
        symbols=("000001.SZ",),
        start_date="20260724",
        end_date="20260724",
    )


def test_fetch_sentiment_from_worker_thread_without_an_event_loop() -> None:
    provider = CrawlerDataProvider(crawler=_Crawler())

    artifact = asyncio.run(asyncio.to_thread(provider.fetch, _query()))

    assert artifact.provider == "Finance-God/Crawler"
    assert artifact.row_count == 1
    assert artifact.records[0]["sentiment_score"] == 62


def test_fetch_sentiment_when_caller_has_a_running_event_loop() -> None:
    provider = CrawlerDataProvider(crawler=_Crawler())

    async def fetch():
        return provider.fetch(_query())

    artifact = asyncio.run(fetch())

    assert artifact.provider == "Finance-God/Crawler"
    assert artifact.row_count == 1
