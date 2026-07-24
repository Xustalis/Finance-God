"""The continuous self-iteration learning loop and its composition root.

``ContinuousLearningLoop`` runs one cycle at a time forever: it gathers
observations from the active source, injects the accumulated lessons as prior
evidence, routes a single request through the current agent runtime, distills
the response into new lessons, persists them, and rewrites the knowledge
snapshot.  ``LearningRuntime.from_environment`` wires the production loop with
the real ARK-backed orchestrator and best-effort PandaData market access,
degrading gracefully (never fabricating data) when a dependency is missing.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from research_runtime.models import EvidenceRecord

from finance_god.orchestration.multi_agent import MultiAgentRuntime
from finance_god.orchestration.orchestrator import Orchestrator

from .contracts import (
    _LESSON_TOPIC_BACKTEST,
    _LESSON_TOPIC_MARKET,
    _LESSON_TOPIC_STRATEGY,
    AgentGateway,
    CycleReport,
    KnowledgeStore,
    LearningConfig,
    ObservationSource,
)
from .contracts import _now as _utcnow
from .gateway import OrchestratorAgentGateway
from .knowledge_store import JsonKnowledgeStore
from .sources import (
    BacktestObservationSource,
    MarketObservationSource,
    RollingPredictionObservationSource,
    StrategyBacktestObservationSource,
)
from .synthesizer import LessonSynthesizer

_LOGGER = logging.getLogger(__name__)

_AGENT_REQUEST_EVIDENCE_LIMIT = 50
_TOPIC_SHORT = {
    _LESSON_TOPIC_MARKET: "mkt",
    _LESSON_TOPIC_BACKTEST: "bt",
    _LESSON_TOPIC_STRATEGY: "strat",
}
_TOPIC_SUBJECT = {
    _LESSON_TOPIC_MARKET: "分析最新真实行情，只形成有证据和失效条件的研究结论",
    _LESSON_TOPIC_BACKTEST: (
        "执行 past-only 方向预测；摘要首行必须严格输出 "
        "PREDICTION: UP、PREDICTION: DOWN 或 PREDICTION: FLAT"
    ),
    _LESSON_TOPIC_STRATEGY: "审阅确定性 walk-forward 回测的稳健性和失效条件",
}


class ContinuousLearningLoop:
    """Drive the observe -> reason -> distill -> persist -> feed-back cycle."""

    def __init__(
        self,
        *,
        config: LearningConfig,
        store: KnowledgeStore,
        sources: list[ObservationSource],
        gateway: AgentGateway,
        synthesizer: LessonSynthesizer | None = None,
    ) -> None:
        if not sources:
            raise ValueError("at least one observation source is required")
        self._config = config
        self._store = store
        self._sources = sources
        self._gateway = gateway
        self._synthesizer = synthesizer or LessonSynthesizer()

    async def run(
        self,
        *,
        stop_event: asyncio.Event,
        start_cycle: int = 0,
        max_cycles: int | None = None,
    ) -> None:
        cycle = start_cycle
        processed = 0
        while not stop_event.is_set():
            if max_cycles is not None and processed >= max_cycles:
                break
            try:
                await self.run_cycle(cycle)
            except Exception:  # noqa: BLE001 - one bad cycle must not kill the loop
                _LOGGER.exception("learning cycle %d failed", cycle)
            cycle += 1
            processed += 1
            if stop_event.is_set():
                break
            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=self._config.interval_seconds
                )
            except asyncio.TimeoutError:
                continue

    async def run_cycle(self, cycle: int) -> CycleReport:
        source = self._sources[cycle % len(self._sources)]
        topic = source.topic
        run_id = f"{self._config.run_id_prefix}-{_TOPIC_SHORT.get(topic, 'x')}-{cycle:06d}"
        report = CycleReport(cycle=cycle, topic=topic, run_id=run_id)

        observed = (await source.observe(cycle))[: self._config.max_observations]
        report.observation_ids = [item.identifier for item in observed]
        observations = [
            item
            for item in observed
            if item.degraded or not self._store.seen_observation(item.identifier)
        ]
        if observed and not observations:
            report.status = "skipped"
            report.notes.append("行情与上一轮相同，跳过重复 Agent 调用。")
            report.finished_at = _utcnow()
            self._store.record_cycle(report)
            return report
        if not observations or all(item.degraded for item in observations):
            report.status = "degraded"
            report.notes.append("本轮观测不可用于学习，已记录并等待下一次真实数据。")
            report.finished_at = _utcnow()
            self._store.record_cycle(report)
            return report

        prior = self._store.prior_evidence(
            limit=self._config.max_prior_lessons,
            topic=topic,
            verified_only=True,
        )
        report.prior_lesson_ids = [item.identifier for item in prior]

        evidence = self._assemble_evidence(prior, observations)
        if not evidence:
            report.status = "degraded"
            report.notes.append("本轮无可用证据（观测为空且无历史经验），跳过 Agent 调用。")
            report.finished_at = _utcnow()
            self._store.record_cycle(report)
            return report

        subject = (
            f"持续学习-{topic}-第{cycle}轮："
            f"{_TOPIC_SUBJECT.get(topic, '基于证据完成研究')}"
        )
        try:
            run = await self._gateway.reason(
                run_id=run_id,
                subject=subject,
                task_type="research",
                evidence=evidence,
                max_agents=self._config.max_agents,
            )
        except Exception as error:  # noqa: BLE001 - surfaced as an auditable note
            report.status = "error"
            report.notes.append(f"Agent 执行失败：{type(error).__name__}: {error}")
            report.finished_at = _utcnow()
            self._store.record_cycle(report)
            raise

        report.agent_ids = [result.agent_id for result in run.results]
        lessons = self._synthesizer.synthesize(
            run=run, cycle=cycle, topic=topic, observations=observations
        )
        self._store.record_lessons(lessons)
        report.new_lesson_ids = [lesson.lesson_id for lesson in lessons]
        if any(item.degraded for item in observations):
            report.notes.append("部分观测处于降级状态（数据缺失或陈旧）。")
        self._store.write_snapshot()
        report.finished_at = _utcnow()
        self._store.record_cycle(report)
        return report

    def _assemble_evidence(
        self,
        prior: list[EvidenceRecord],
        observations: list,
    ) -> list[EvidenceRecord]:
        observation_evidence = [item.to_evidence() for item in observations]
        combined: list[EvidenceRecord] = [*observation_evidence, *prior]
        seen: set[str] = set()
        unique: list[EvidenceRecord] = []
        for record in combined:
            if record.identifier in seen:
                continue
            seen.add(record.identifier)
            unique.append(record)
            if len(unique) >= _AGENT_REQUEST_EVIDENCE_LIMIT:
                break
        return unique


class _ServiceBarReader:
    """Read-only bar access for learning observation.

    Uses the market-data service's public read-only boundary so continuous
    observation does not create durable data-quality workflow runs on every
    poll. Quality decisions are surfaced verbatim to the observer.
    """

    def __init__(self, service: object) -> None:
        self._service = service

    def read_bars(self, symbol: str, *, limit: int) -> object:
        return self._service.read_bars(symbol, limit=limit)


class LearningRuntime:
    """Production composition root for the continuous learning loop."""

    def __init__(
        self,
        *,
        config: LearningConfig,
        store: JsonKnowledgeStore,
        loop: ContinuousLearningLoop,
        startup_notes: list[str],
    ) -> None:
        self.config = config
        self.store = store
        self.loop = loop
        self.startup_notes = startup_notes

    @classmethod
    def from_environment(
        cls,
        *,
        config: LearningConfig | None = None,
        orchestrator: Orchestrator | None = None,
    ) -> "LearningRuntime":
        resolved = config or LearningConfig.from_environment()
        store = JsonKnowledgeStore(resolved.knowledge_dir)
        # The learning worker supplies a time-bounded evidence pack itself.
        # Disabling runtime-side data tools prevents holdout leakage while
        # retaining the same registry, router, prompts, and ARK model path.
        configured_orchestrator = orchestrator or Orchestrator(
            MultiAgentRuntime.from_environment(
                enable_panda_data=False,
                enable_finrobot_metrics=False,
            )
        )
        gateway = OrchestratorAgentGateway(
            configured_orchestrator
        )
        sources: list[ObservationSource] = []
        notes: list[str] = []
        market_reader = (
            cls._build_market_reader(notes)
            if resolved.enable_market or resolved.enable_backtest
            else None
        )

        if resolved.enable_market and market_reader is not None:
            sources.append(
                MarketObservationSource(
                    market_reader,
                    symbols=resolved.symbols,
                    bar_limit=resolved.market_bar_limit,
                )
            )

        if resolved.enable_backtest:
            if market_reader is not None:
                sources.extend(
                    [
                        RollingPredictionObservationSource(
                            market_reader,
                            symbols=resolved.symbols,
                            bar_limit=resolved.market_bar_limit,
                        ),
                        StrategyBacktestObservationSource(
                            market_reader,
                            symbols=resolved.symbols,
                            bar_limit=resolved.market_bar_limit,
                            transaction_cost_bps=(
                                resolved.strategy_transaction_cost_bps
                            ),
                        ),
                    ]
                )
            backtest_source = cls._build_backtest_source(resolved, notes)
            if backtest_source is not None:
                sources.append(backtest_source)

        if not sources:
            raise RuntimeError(
                "no learning observation source is available; "
                "enable market or backtest and check credentials/artifacts"
            )

        loop = ContinuousLearningLoop(
            config=resolved,
            store=store,
            sources=sources,
            gateway=gateway,
        )
        return cls(
            config=resolved,
            store=store,
            loop=loop,
            startup_notes=notes,
        )

    @staticmethod
    def _build_market_reader(
        notes: list[str],
    ) -> _ServiceBarReader | None:
        try:
            from finance_god.market_data import MarketDataService

            service = MarketDataService.from_environment()
        except Exception as error:  # noqa: BLE001 - degrade without market data
            notes.append(
                f"市场行情源不可用（{type(error).__name__}）；本次仅运行其余数据源。"
            )
            return None
        return _ServiceBarReader(service)

    @staticmethod
    def _build_backtest_source(
        config: LearningConfig, notes: list[str]
    ) -> BacktestObservationSource | None:
        override = os.getenv("FINANCE_GOD_BACKTEST_DIR")
        if override:
            backtest_dir = Path(override)
        else:
            workspace_root = Path(__file__).resolve().parents[3]
            backtest_dir = workspace_root / "artifacts" / "backtest"
        source = BacktestObservationSource(backtest_dir)
        if not source.available():
            notes.append(
                f"回测数据目录不可用或为空：{backtest_dir}；跳过回测学习。"
            )
            return None
        return source


__all__ = [
    "ContinuousLearningLoop",
    "LearningRuntime",
]
