"""Deterministic adapters for workflow composition experiments.

These adapters never call a model provider or a market-data service. They are
intentionally isolated from production construction in ``MultiAgentRuntime``.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from research_runtime import AgentRunner
from research_runtime.models import DataArtifact, DataQuery, PandaDataDataset

from finance_god.orchestration.multi_agent import MultiAgentRuntime
from finance_god.orchestration.orchestrator import Orchestrator

_EXPERIMENT_TIME = datetime(2026, 7, 23, 8, 0, tzinfo=timezone.utc)


class OfflineExperimentChatClient:
    """Return structured evidence-linked output without an external LLM call."""

    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        agent_match = re.search(r"(?m)^Agent: ([^\n]+)$", user_prompt)
        evidence_matches = re.findall(r"(?m)^\[([A-Za-z0-9_-]+)\]", user_prompt)
        if agent_match is None:
            raise ValueError("experiment prompt did not contain an Agent identifier")
        if not evidence_matches:
            raise ValueError("experiment prompt did not contain an evidence identifier")
        agent_id = agent_match.group(1)
        evidence_id = evidence_matches[-1]
        return json.dumps(
            {
                "summary": f"离线实验结果：{agent_id} 已完成其限定角色的证据审阅。",
                "claims": [
                    {
                        "kind": "fact",
                        "statement": f"{agent_id} 的判断仅基于已提供证据。",
                        "evidence_ids": [evidence_id],
                        "unknowns": ["未接入实时模型与外部市场数据。"],
                        "invalidation_conditions": ["输入证据版本发生变化。"],
                    }
                ],
                "proposed_actions": [f"人工复核 {agent_id} 的实验输出。"],
            },
            ensure_ascii=False,
        )


class OfflineExperimentDataProvider:
    """Return schema-valid deterministic rows for Panda monitor experiments."""

    def fetch(self, query: DataQuery) -> DataArtifact:
        records = self._records(query)
        return DataArtifact(
            provider="offline-experiment",
            query=query,
            retrieved_at=_EXPERIMENT_TIME,
            row_count=len(records),
            columns=sorted({key for record in records for key in record}),
            records=records,
        )

    @staticmethod
    def _records(query: DataQuery) -> list[dict[str, object]]:
        symbol = query.symbols[0] if query.symbols else "000001.SZ"
        records_by_dataset: dict[PandaDataDataset, list[dict[str, object]]] = {
            PandaDataDataset.MARKET_BARS: [
                {
                    "symbol": symbol,
                    "date": query.start_date,
                    "open": 100.0,
                    "high": 102.0,
                    "low": 99.0,
                    "close": 101.0,
                    "volume": 1_000_000,
                },
                {
                    "symbol": symbol,
                    "date": query.end_date,
                    "open": 101.0,
                    "high": 103.0,
                    "low": 100.0,
                    "close": 102.0,
                    "volume": 1_100_000,
                },
            ],
            PandaDataDataset.MARGIN: [
                {
                    "symbol": symbol,
                    "date": query.start_date,
                    "total_balance": 100.0,
                    "short_balance": 10.0,
                },
                {
                    "symbol": symbol,
                    "date": query.end_date,
                    "total_balance": 110.0,
                    "short_balance": 12.0,
                },
            ],
            PandaDataDataset.LHB_LIST: [
                {
                    "symbol": symbol,
                    "date": query.start_date,
                    "amount": 10_000_000.0,
                    "change_rate": 0.02,
                    "turnover": 0.03,
                }
            ],
            PandaDataDataset.FUTURE_DOMINANT_CORR: [
                {"pair": "IF.CFE/IC.CFE", "correlation": 0.72},
                {"pair": "IF.CFE/IH.CFE", "correlation": 0.81},
            ],
            PandaDataDataset.OPTION_IMPLIED_VOLATILITY: [
                {
                    "date": query.end_date,
                    "symbol": symbol,
                    "implied_volatility": 0.24,
                }
            ],
            PandaDataDataset.OPTION_UNDERLYING_VOLATILITY: [
                {
                    "date": query.end_date,
                    "symbol": symbol,
                    "close": 4.2,
                    "period": query.volatility_period,
                    "historical_volatility": 0.19,
                }
            ],
        }
        return records_by_dataset[query.dataset]


def build_offline_orchestrator(*, max_concurrency: int = 4) -> Orchestrator:
    """Build an Orchestrator suitable only for deterministic local experiments."""
    runner = AgentRunner(
        chat_client=OfflineExperimentChatClient(),
        data_provider=OfflineExperimentDataProvider(),
        max_concurrency=max_concurrency,
    )
    return Orchestrator(multi_agent_runtime=MultiAgentRuntime(runner))
