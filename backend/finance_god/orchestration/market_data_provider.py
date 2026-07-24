"""Finance-God-owned PandaData bridge for deterministic agent monitors."""

from __future__ import annotations

from research_runtime.models import DataArtifact, DataQuery, PandaDataDataset

from finance_god.market_data import (
    DataFrequency,
    MarketDataResponseError,
    MonitorDataset,
    PandaDataAdapter,
    ReleaseState,
)


class FinanceGodMarketDataProvider:
    """Expose only normalized Finance-God market data to the agent runtime."""

    def __init__(self, adapter: PandaDataAdapter) -> None:
        self._adapter = adapter

    @classmethod
    def from_environment(cls) -> "FinanceGodMarketDataProvider":
        return cls(PandaDataAdapter.from_environment())

    def fetch(self, query: DataQuery) -> DataArtifact:
        if query.dataset is PandaDataDataset.MARKET_BARS:
            return self._fetch_bars(query)
        dataset = MonitorDataset(query.dataset.value)
        envelope = self._adapter.fetch_monitor_facts(
            dataset=dataset,
            symbols=tuple(query.symbols),
            start_date=query.start_date,
            end_date=query.end_date,
            volatility_period=query.volatility_period,
        )
        if not envelope.items:
            self._raise_empty(query, envelope.diagnostics[-1].message)
        records = [
            {field.name: field.value for field in item.fields}
            for item in envelope.items
        ]
        return DataArtifact(
            provider="Finance-God/PandaData",
            query=query,
            retrieved_at=max(item.source.ingested_at for item in envelope.items),
            row_count=len(records),
            columns=sorted({key for record in records for key in record}),
            records=records,
        )

    def _fetch_bars(self, query: DataQuery) -> DataArtifact:
        if len(query.symbols) != 1:
            raise ValueError("market bar monitor data requires exactly one symbol")
        instrument = self._adapter.instrument_master.resolve(query.symbols[0])
        envelope = self._adapter.fetch_bars(
            instrument,
            frequency=DataFrequency.DAILY,
            start_date=query.start_date,
            end_date=query.end_date,
            limit=1_000,
            release_state=ReleaseState.RELEASED,
        )
        if not envelope.items:
            self._raise_empty(query, envelope.diagnostics[-1].message)
        records = [
            {
                "symbol": item.instrument.symbol,
                "date": item.source.data_time.strftime("%Y%m%d"),
                "open": float(item.open),
                "high": float(item.high),
                "low": float(item.low),
                "close": float(item.close),
                "volume": float(item.volume),
            }
            for item in envelope.items
        ]
        return DataArtifact(
            provider="Finance-God/PandaData",
            query=query,
            retrieved_at=max(item.source.ingested_at for item in envelope.items),
            row_count=len(records),
            columns=sorted({key for record in records for key in record}),
            records=records,
        )

    @staticmethod
    def _raise_empty(query: DataQuery, detail: str) -> None:
        raise MarketDataResponseError(
            f"normalized PandaData returned no monitor records for {query.identifier}: {detail}"
        )
