"""Crawler-sourced data provider for the agent research runtime.

Bridges CrawlerService sentiment/news data into the DataProvider protocol
so that deterministic agent monitors can consume market sentiment and news
without depending on PandaData's NOT_VERIFIED endpoints.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from research_runtime.models import DataArtifact, DataQuery, EvidenceRecord, PandaDataDataset

from finance_god.crawler.service import CrawlerService

_LOGGER = logging.getLogger(__name__)


class CrawlerDataProvider:
    """Provide crawler-sourced sentiment and news data to the agent runtime.

    Implements the DataProvider protocol expected by AgentRunner.
    Delegates market-bar and option/derivative queries to a fallback provider
    (FinanceGodMarketDataProvider) and handles MARGIN dataset using crawler
    sentiment data (richer than PandaData raw margin balance).
    """

    def __init__(
        self,
        *,
        crawler: CrawlerService | None = None,
        fallback: object | None = None,
    ) -> None:
        self._crawler = crawler or CrawlerService()
        self._fallback = fallback

    def fetch(self, query: DataQuery) -> DataArtifact:
        """Route data queries: MARGIN → crawler sentiment, others → fallback."""
        if query.dataset == PandaDataDataset.MARGIN:
            return self._fetch_sentiment(query)
        if self._fallback is not None:
            return self._fallback.fetch(query)  # type: ignore[union-attr]
        raise ValueError(
            f"CrawlerDataProvider cannot serve dataset={query.dataset.value} "
            f"without a fallback provider"
        )

    def _fetch_sentiment(self, query: DataQuery) -> DataArtifact:
        """Convert crawler MarketSentiment into a DataArtifact for agents."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    sentiment = pool.submit(
                        lambda: asyncio.run(self._crawler.get_sentiment())
                    ).result(timeout=20)
            else:
                sentiment = asyncio.run(self._crawler.get_sentiment())
        except Exception as exc:
            _LOGGER.warning("CrawlerDataProvider sentiment fetch failed: %s", exc)
            # If crawler fails and fallback exists, try PandaData margin
            if self._fallback is not None:
                return self._fallback.fetch(query)  # type: ignore[union-attr]
            raise

        # Convert MarketSentiment into flat records for agent consumption
        records: list[dict[str, object]] = [
            {
                "symbol": "A_SHARE_MARKET",
                "date": datetime.now(timezone.utc).strftime("%Y%m%d"),
                "sentiment_score": sentiment.score,
                "sentiment_level": sentiment.level.value,
                "north_flow": sentiment.north_flow,
                "up_ratio": sentiment.breadth.up_ratio,
                "up_count": sentiment.breadth.up_count,
                "down_count": sentiment.breadth.down_count,
                "limit_up": sentiment.breadth.limit_up,
                "limit_down": sentiment.breadth.limit_down,
                "total_volume": sentiment.total_volume,
                "data_source": sentiment.data_source,
            }
        ]
        # Add sector flow records
        for sf in sentiment.sector_flows[:10]:
            records.append({
                "symbol": sf.sector_name,
                "date": datetime.now(timezone.utc).strftime("%Y%m%d"),
                "sector_change_percent": sf.change_percent,
                "sector_net_inflow": sf.net_inflow,
                "sector_main_inflow": sf.main_inflow,
                "data_source": "crawler_sector_flow",
            })

        columns = sorted({key for record in records for key in record})
        return DataArtifact(
            provider="Finance-God/Crawler",
            query=query,
            retrieved_at=datetime.now(timezone.utc),
            row_count=len(records),
            columns=columns,
            records=records,
        )

    def compile_evidence(self, artifact: DataArtifact) -> EvidenceRecord:
        """Compile a readable evidence record from a crawler data artifact."""
        query = artifact.query
        if artifact.provider == "Finance-God/Crawler":
            first = artifact.records[0] if artifact.records else {}
            score = first.get("sentiment_score", "n/a")
            level = first.get("sentiment_level", "n/a")
            north = first.get("north_flow", "n/a")
            return EvidenceRecord(
                identifier=f"CRAWLER_{query.identifier.upper()}",
                source=f"Finance-God Crawler sentiment ({query.identifier})",
                excerpt=(
                    f"Market sentiment: score={score}, level={level}, "
                    f"north_flow={north}B CNY; "
                    f"period={query.start_date}-{query.end_date}; "
                    f"rows={artifact.row_count}"
                ),
            )
        return EvidenceRecord(
            identifier=f"CRAWLER_{query.identifier.upper()}",
            source=f"Finance-God Crawler ({query.identifier})",
            excerpt=f"Crawler data: rows={artifact.row_count}",
        )
