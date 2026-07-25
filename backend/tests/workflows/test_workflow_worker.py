"""Unit tests for the Workflow Worker claim/execute loop."""

from __future__ import annotations

import asyncio
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from research_runtime import (
    AgentPlan,
    AgentRegistry,
    AgentResult,
    AgentRun,
    Claim,
    ExecutionProfile,
)
from research_runtime.contracts import AgentAssignment
from research_runtime.models import PandaDataDataset

from finance_god.agents.catalog import AgentGovernanceCatalog
from finance_god.agents.contracts import WorkflowKey
from finance_god.application.candidate_service import CandidateResponse
from finance_god.application.portfolio_query import PortfolioPosition, PortfolioView
from finance_god.application.workflow_worker import (
    MarketAlertContext,
    OpenControls,
    WorkflowWorker,
    _agent_payload,
    worker_supports,
)
from finance_god.crawler.models import CrawlerResult, IndustryNews
from finance_god.domain.models import VersionReference, WorkflowRunStatus
from finance_god.market_data.monitor import (
    AlertKind,
    AlertSeverity,
    MarketAlert,
    MarketSnapshot,
)
from finance_god.orchestration.task_plans import TaskPlanFactory
from finance_god.orchestration.workflow_commands import (
    WorkflowCommandService,
    WorkflowCreateCommand,
)
from finance_god.orchestration.workflow_executor import NodeExecutionContext
from finance_god.orchestration.workflow_registry import FormalWorkflowRegistry
from tests.workflows.support import (
    AdvancingClock,
    AsyncMemoryWorkflowRepository,
    SequenceRunIds,
)

NOW = datetime(2026, 7, 24, tzinfo=timezone.utc)
INPUT = (
    VersionReference(
        object_type="market_snapshot",
        object_id="XNAS:AAPL",
        version="v1",
    ),
)
CONTEXT_INPUT = (
    VersionReference(
        object_type="instrument_context",
        object_id="000001.SZ",
        version="v1",
    ),
)


class AgentPayloadContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.context = NodeExecutionContext(
            run_id="workflow-run-payload",
            owner_id="user-1",
            workflow_key=WorkflowKey.MARKET_CONTEXT,
            workflow_version="finance-god-workflows-v2",
            final_artifact_type="MarketContext",
            plan_reference=VersionReference(
                object_type="TaskPlan",
                object_id="plan-1",
                version="v1",
            ),
            input_versions=(
                VersionReference(
                    object_type="instrument_context",
                    object_id="000001.SZ",
                    version="v1",
                ),
            ),
            completed_artifacts=(),
        )

    def test_market_regime_uses_explicit_broad_market_proxies(self) -> None:
        payload = _agent_payload(
            "quantskills:agent-market-regime-monitor",
            self.context,
            NOW,
        )

        self.assertEqual(payload["symbol"], "000001.SZ")
        self.assertEqual(payload["index_symbol"], "000300.SH")
        self.assertEqual(payload["option_underlying"], "510300.SH")
        self.assertEqual(payload["response_language"], "zh-CN")
        self.assertIn("涨跌幅必须说明计算区间或基准", payload["response_requirements"])

    def test_market_regime_uses_the_upstream_observation_session(self) -> None:
        upstream = datetime.fromisoformat("2026-07-23T15:00:00+08:00")

        payload = _agent_payload(
            "quantskills:agent-market-regime-monitor",
            self.context,
            upstream,
        )

        self.assertEqual(payload["end_date"], "20260723")
        self.assertEqual(payload["start_date"], "20260623")

    def test_derivatives_monitor_does_not_treat_stock_as_option_underlying(
        self,
    ) -> None:
        payload = _agent_payload(
            "quantskills:agent-derivatives-skew-sentiment-monitor",
            self.context,
            NOW,
        )

        self.assertEqual(payload["option_underlying"], "510300.SH")
        self.assertNotEqual(
            payload["option_underlying"],
            self.context.input_versions[0].object_id,
        )

    def test_prompt_agents_receive_chinese_output_contract(self) -> None:
        payload = _agent_payload(
            "tradingagents:market_analyst",
            self.context,
            NOW,
        )

        self.assertEqual(payload["response_language"], "zh-CN")
        self.assertIn("只补充本角色新增的信息", payload["response_requirements"])
        self.assertIn("先给结论或当前判断", payload["response_requirements"])
        self.assertIn("不得为了行文流畅补造事实", payload["response_requirements"])
        self.assertIn("值得注意的是", payload["response_requirements"])

    def test_manager_receives_complete_synthesis_contract(self) -> None:
        payload = _agent_payload(
            "tradingagents:research_manager",
            self.context,
            NOW,
        )

        self.assertIn("可独立阅读的完整中文综合结论", payload["response_requirements"])
        self.assertIn("合并等价内容", payload["response_requirements"])


class _MemoryUow:
    def __init__(
        self,
        repository: AsyncMemoryWorkflowRepository,
        commits: list[str],
    ) -> None:
        self.workflows = repository
        self._commits = commits

    async def commit(self) -> None:
        self._commits.append("commit")


class _Runtime:
    def __init__(
        self,
        *,
        fail: bool = False,
        started: asyncio.Event | None = None,
        release: asyncio.Event | None = None,
    ) -> None:
        self.fail = fail
        self.requests = []
        self.started = started
        self.release = release
        self._registry = AgentRegistry()

    @property
    def available_resources(self) -> frozenset[str]:
        return frozenset({"workspace", *(item.value for item in PandaDataDataset)})

    def list_agents(self):
        return self._registry.list()

    async def run(self, request):
        self.requests.append(request)
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            await self.release.wait()
        if self.fail:
            raise RuntimeError("model unavailable")
        agent_id = request.requested_agent_ids[0]
        evidence_id = request.evidence[0].identifier
        return AgentRun(
            run_id=request.run_id,
            plan=AgentPlan(
                run_id=request.run_id,
                assignments=[
                    AgentAssignment(
                        agent_id=agent_id,
                        reason="test runtime",
                    )
                ],
            ),
            results=[
                AgentResult(
                    agent_id=agent_id,
                    summary=f"real result from {agent_id}",
                    claims=[
                        Claim(
                            claim_id=f"{agent_id}:claim-1",
                            author_agent_id=agent_id,
                            kind="inference",
                            statement="Evidence-bound test result.",
                            evidence_ids=[evidence_id],
                        )
                    ],
                )
            ],
        )


class WorkflowWorkerTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.catalog = AgentGovernanceCatalog()
        self.registry = FormalWorkflowRegistry.build_default(self.catalog)
        self.repository = AsyncMemoryWorkflowRepository()
        self.commands = WorkflowCommandService(
            registry=self.registry,
            repository=self.repository,
            run_ids=SequenceRunIds(),
        )
        self.runtime = _Runtime()
        self.recorded = []
        self.candidate_calls = []
        self.clock = AdvancingClock()
        self.commits = []
        self.alert_context_error: Exception | None = None
        self.candidate_unavailable_reason: str | None = None
        self.alert_context = MarketAlertContext(
            snapshot=MarketSnapshot(
                symbol="000001.SZ",
                name="平安银行",
                last=Decimal("11.12"),
                change_percent=Decimal("0.061"),
                provider_time="2026-07-24T09:30:00+08:00",
                frequency="1min",
                freshness="realtime",
                retrieved_at=NOW,
            ),
            latest_alert=MarketAlert(
                alert_id="alert-000001",
                symbol="000001.SZ",
                name="平安银行",
                kind=AlertKind.SURGE,
                severity=AlertSeverity.WARNING,
                change_percent=Decimal("0.061"),
                last=Decimal("11.12"),
                message="平安银行重大行情提醒",
                provider_time="2026-07-24T09:30:00+08:00",
                detected_at=NOW,
            ),
            observed_at=NOW,
        )

        @asynccontextmanager
        async def uow_factory():
            yield _MemoryUow(self.repository, self.commits)

        self.worker = WorkflowWorker(
            uow_factory=uow_factory,
            runtime_provider=self._runtime_provider,
            evidence_recorder=self._record_evidence,
            candidate_provider=self._candidate_provider,
            market_context_provider=self._market_context_provider,
            market_history_provider=self._market_history_provider,
            information_facts_provider=self._market_facts_provider,
            sentiment_facts_provider=self._market_facts_provider,
            crawler_context_provider=self._crawler_context_provider,
            market_alert_context_provider=self._market_alert_context_provider,
            portfolio_provider=self._portfolio_provider,
            registry=self.registry,
            catalog=self.catalog,
            controls=OpenControls(),
            clock=self.clock,
            batch_size=2,
        )

    async def _runtime_provider(self):
        return self.runtime

    async def _record_evidence(self, **payload) -> None:
        self.recorded.append(payload)

    async def _candidate_provider(self, owner_id, now, profile):
        self.candidate_calls.append((owner_id, profile))
        return CandidateResponse(
            generated_at=now,
            rule_version="simulation-rules-v1",
            purpose_summary="候选不是买入指令。",
            profile_version=3,
            directions=("equities",),
            unavailable_reason=self.candidate_unavailable_reason,
        )

    async def _market_context_provider(self, symbols: list[str]):
        self.assertEqual(symbols, ["000001.SZ"])
        quote = SimpleNamespace(
            symbol="000001.SZ",
            provider="PandaData",
            last=Decimal("11.1"),
            change_percent=Decimal("0.18"),
            provider_time="2026-07-24T15:00:00+08:00",
            retrieved_at=NOW,
            frequency="1m",
            freshness="unknown",
            session_alignment="latest_released_session",
            market_status="released",
        )
        return SimpleNamespace(quotes=(quote,), errors={})

    async def _market_history_provider(
        self,
        symbol: str,
        *,
        start_date: str,
        end_date: str,
        limit: int,
    ):
        self.assertEqual(symbol, "000001.SZ")
        self.assertEqual(start_date, "20260624")
        self.assertEqual(end_date, "20260724")
        self.assertEqual(limit, 1_000)
        bars = tuple(
            SimpleNamespace(
                time=f"2026-07-{day:02d}T15:00:00+08:00",
                open=Decimal("10"),
                high=Decimal("11.2"),
                low=Decimal("9.8"),
                close=Decimal(f"11.{day - 10}"),
                volume=Decimal("1000"),
                provider_time=f"2026-07-{day:02d}T15:00:00+08:00",
                freshness="unknown",
            )
            for day in range(10, 20)
        )
        return SimpleNamespace(frequency="日频", bars=bars)

    async def _crawler_context_provider(self):
        return CrawlerResult(
            success=True,
            news=[
                IndustryNews(
                    title="银行业公开资讯",
                    summary="用于工作流证据注入测试。",
                    source="测试公开源",
                    url="https://example.test/news/1",
                    publish_time=NOW,
                    sector="银行",
                )
            ],
            retrieved_at=NOW,
        )

    async def _market_facts_provider(self, symbol: str, **kwargs):
        self.assertEqual(symbol, "000001.SZ")
        self.assertTrue(kwargs)
        return SimpleNamespace(
            facts=(),
            fact_kind=(
                "company_disclosure" if "start_quarter" in kwargs else "margin_balance"
            ),
            symbol=symbol,
            requested_at=NOW,
        )

    async def _market_alert_context_provider(self, symbol: str):
        if self.alert_context_error is not None:
            raise self.alert_context_error
        self.assertEqual(symbol, "000001.SZ")
        return self.alert_context

    async def _portfolio_provider(self, owner_id: str) -> PortfolioView:
        self.assertEqual(owner_id, "user-1")
        return PortfolioView(
            account_id="simulation-user-1",
            owner_id=owner_id,
            as_of=NOW,
            rule_version="simulation-rules-v1",
            positions=(
                PortfolioPosition(
                    instrument_id="000001.SZ",
                    currency="CNY",
                    quantity=Decimal("100"),
                    settled_quantity=Decimal("100"),
                    frozen_quantity=Decimal("0"),
                    available_quantity=Decimal("100"),
                    cost_basis_rmb=Decimal("1000"),
                    average_cost_rmb=Decimal("10"),
                    realized_pnl_rmb=Decimal("0"),
                    revision=1,
                ),
            ),
        )

    async def _queue(
        self,
        *,
        key: WorkflowKey,
        suffix: str,
        input_versions=INPUT,
        owner_id: str = "user-1",
    ) -> str:
        receipt = await self.commands.create(
            WorkflowCreateCommand(
                idempotency_key=f"worker-{suffix}",
                workflow_key=key,
                request_intent=f"Worker execute {key.value}.",
                owner_id=owner_id,
                scope={"workspace": "desk-1"},
                input_versions=input_versions,
                requested_at=NOW,
            )
        )
        return receipt.run.run_id

    async def test_process_once_drives_queued_run_to_terminal(self) -> None:
        run_id = await self._queue(
            key=WorkflowKey.COMPANY_RESEARCH,
            suffix="company",
            input_versions=CONTEXT_INPUT,
        )
        finished = await self.worker.process_once()
        self.assertEqual(finished, 1)
        run = await self.repository.get(run_id)
        assert run is not None
        self.assertNotEqual(run.status, WorkflowRunStatus.QUEUED)
        self.assertNotEqual(run.status, WorkflowRunStatus.RUNNING)
        self.assertIn(
            run.status,
            {
                WorkflowRunStatus.COMPLETED,
                WorkflowRunStatus.ATTENTION_REQUIRED,
                WorkflowRunStatus.FAILED,
                WorkflowRunStatus.TIMED_OUT,
                WorkflowRunStatus.BLOCKED,
            },
        )
        self.assertTrue(self.runtime.requests)
        if run.status is WorkflowRunStatus.COMPLETED:
            self.assertEqual(len(self.recorded), 2)
            self.assertEqual(self.recorded[-1]["object_id"], run_id)
            self.assertEqual(
                self.recorded[-1]["object_type"],
                run.final_artifact.object_type,
            )
            self.assertTrue(self.recorded[-1]["run"].results[0].evidence)

    async def test_support_probe_rejects_unconnected_deterministic_service(
        self,
    ) -> None:
        self.assertTrue(worker_supports(self.registry.get(WorkflowKey.MARKET_CONTEXT)))
        self.assertFalse(
            worker_supports(self.registry.get(WorkflowKey.PORTFOLIO_CONSTRUCTION))
        )

    async def test_process_once_is_idle_when_queue_empty(self) -> None:
        finished = await self.worker.process_once()
        self.assertEqual(finished, 0)

    async def test_candidate_workflow_uses_deterministic_service_and_records_evidence(
        self,
    ) -> None:
        run_id = await self._queue(
            key=WorkflowKey.RESEARCH_CANDIDATES,
            suffix="candidates",
        )

        finished = await self.worker.process_once()

        self.assertEqual(finished, 1)
        run = await self.repository.get(run_id)
        assert run is not None
        self.assertEqual(run.status, WorkflowRunStatus.COMPLETED)
        self.assertEqual(self.candidate_calls, [("user-1", None)])
        self.assertFalse(self.runtime.requests)
        self.assertEqual(len(self.recorded), 1)
        self.assertIsNone(self.recorded[0]["run"])
        self.assertEqual(
            self.recorded[0]["provider"],
            "finance-god-candidate-scoring",
        )
        self.assertIsNotNone(self.recorded[0]["content"])

    async def test_candidate_workflow_requires_attention_when_profile_is_missing(
        self,
    ) -> None:
        self.candidate_unavailable_reason = "PROFILE_REQUIRED"
        run_id = await self._queue(
            key=WorkflowKey.RESEARCH_CANDIDATES,
            suffix="candidates-profile-required",
        )

        self.assertEqual(await self.worker.process_once(), 1)

        run = await self.repository.get(run_id)
        assert run is not None
        self.assertEqual(run.status, WorkflowRunStatus.ATTENTION_REQUIRED)
        self.assertIsNone(run.final_artifact)
        self.assertEqual(len(self.recorded), 0)

    async def test_portfolio_stress_calculation_passes_its_quality_gate(self) -> None:
        run_id = await self._queue(
            key=WorkflowKey.PORTFOLIO_STRESS,
            suffix="portfolio-stress",
            input_versions=CONTEXT_INPUT,
        )

        self.assertEqual(await self.worker.process_once(), 1)
        run = await self.repository.get(run_id)

        assert run is not None
        self.assertEqual(run.status, WorkflowRunStatus.COMPLETED, run.errors)
        self.assertNotIn("deterministic_quality_gate_failed", run.errors)

    async def test_strategy_monitoring_compares_versions_and_records_evidence(
        self,
    ) -> None:
        inputs = (
            VersionReference(
                object_type="strategy_baseline",
                object_id="mean-reversion-v1",
                version="2026-07-24T15:00:00Z",
            ),
            VersionReference(
                object_type="strategy_snapshot",
                object_id="mean-reversion-v1",
                version="2026-07-25T15:00:00Z",
            ),
        )
        run_id = await self._queue(
            key=WorkflowKey.STRATEGY_MONITORING,
            suffix="strategy-monitor",
            input_versions=inputs,
        )

        self.assertEqual(await self.worker.process_once(), 1)

        run = await self.repository.get(run_id)
        assert run is not None
        self.assertEqual(run.status, WorkflowRunStatus.COMPLETED, run.errors)
        quantspace_request = next(
            request
            for request in self.runtime.requests
            if request.requested_agent_ids == ["quantskills:agent-quantspace"]
        )
        self.assertEqual(quantspace_request.profile, ExecutionProfile.WORKSPACE)
        comparison = next(
            item
            for item in self.recorded
            if item["object_type"] == "StrategyMonitorComparison"
        )
        self.assertEqual(
            comparison["content"]["version_comparisons"],
            [
                {
                    "object_id": "mean-reversion-v1",
                    "baseline_version": "2026-07-24T15:00:00Z",
                    "current_version": "2026-07-25T15:00:00Z",
                    "version_changed": True,
                }
            ],
        )
        self.assertFalse(comparison["content"]["metric_drift_assessed"])

    async def test_event_impact_agents_receive_real_alert_context(self) -> None:
        run_id = await self._queue(
            key=WorkflowKey.EVENT_IMPACT,
            suffix="event-alert",
            input_versions=CONTEXT_INPUT,
        )

        self.assertEqual(await self.worker.process_once(), 1)

        run = await self.repository.get(run_id)
        assert run is not None
        self.assertEqual(run.status, WorkflowRunStatus.COMPLETED)
        first_evidence = self.runtime.requests[0].evidence
        alert_evidence = next(
            item
            for item in first_evidence
            if item.identifier == "market-alert-context-000001.SZ"
        )
        self.assertIn("last=11.12", alert_evidence.excerpt)
        self.assertIn("change_percent=0.061", alert_evidence.excerpt)
        self.assertIn("alert_id=alert-000001", alert_evidence.excerpt)
        self.assertIn("provider_time=", alert_evidence.excerpt)
        crawler_evidence = next(
            item for item in first_evidence if item.identifier == "crawler-news"
        )
        self.assertIn("银行业公开资讯", crawler_evidence.excerpt)
        self.assertTrue(
            any(item["object_type"] == "MarketAlertContext" for item in self.recorded)
        )

    async def test_market_context_agents_receive_target_interval_daily_bars(
        self,
    ) -> None:
        run_id = await self._queue(
            key=WorkflowKey.MARKET_CONTEXT,
            suffix="market-context-history",
            input_versions=CONTEXT_INPUT,
        )

        self.assertEqual(await self.worker.process_once(), 1)

        run = await self.repository.get(run_id)
        assert run is not None
        self.assertEqual(run.status, WorkflowRunStatus.COMPLETED)
        history = next(
            item
            for item in self.runtime.requests[0].evidence
            if item.identifier == "target-market-bars-000001.SZ"
        )
        self.assertIn("requested_range=20260624-20260724", history.excerpt)
        self.assertIn("row_count=10", history.excerpt)
        self.assertIn("close=11.9", history.excerpt)
        evidence_by_id = {
            item.identifier: item for item in self.runtime.requests[0].evidence
        }
        self.assertIn("company_disclosure-000001.SZ", evidence_by_id)
        self.assertIn("margin_balance-000001.SZ", evidence_by_id)
        self.assertIn(
            '"row_count":0', evidence_by_id["margin_balance-000001.SZ"].excerpt
        )

    async def test_event_impact_can_confirm_no_recorded_alert(self) -> None:
        self.alert_context = MarketAlertContext(
            snapshot=self.alert_context.snapshot,
            latest_alert=None,
            observed_at=NOW,
        )
        run_id = await self._queue(
            key=WorkflowKey.EVENT_IMPACT,
            suffix="event-no-alert",
            input_versions=CONTEXT_INPUT,
        )

        await self.worker.process_once()

        run = await self.repository.get(run_id)
        assert run is not None
        self.assertEqual(run.status, WorkflowRunStatus.COMPLETED)
        alert_evidence = next(
            item
            for item in self.runtime.requests[0].evidence
            if item.identifier == "market-alert-context-000001.SZ"
        )
        self.assertIn("alert_status=none_recorded", alert_evidence.excerpt)
        self.assertIn(
            "系统未记录 000001.SZ 的重大行情提醒",
            next(
                item["conclusion"]
                for item in self.recorded
                if item["object_type"] == "MarketAlertContext"
            ),
        )

    async def test_event_impact_fails_when_alert_context_read_fails(self) -> None:
        self.alert_context_error = RuntimeError("database unavailable")
        run_id = await self._queue(
            key=WorkflowKey.EVENT_IMPACT,
            suffix="event-alert-failure",
            input_versions=CONTEXT_INPUT,
        )

        await self.worker.process_once()

        run = await self.repository.get(run_id)
        assert run is not None
        self.assertEqual(run.status, WorkflowRunStatus.FAILED)
        self.assertFalse(self.runtime.requests)
        self.assertTrue(
            any("market alert context failed" in item for item in run.errors)
        )

    async def test_running_claim_is_committed_before_agent_finishes(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        self.runtime = _Runtime(started=started, release=release)
        run_id = await self._queue(
            key=WorkflowKey.COMPANY_RESEARCH,
            suffix="visible-claim",
            input_versions=CONTEXT_INPUT,
        )

        processing = asyncio.create_task(self.worker.process_once())
        await asyncio.wait_for(started.wait(), timeout=1)

        run = await self.repository.get(run_id)
        assert run is not None
        self.assertEqual(run.status, WorkflowRunStatus.RUNNING)
        self.assertGreaterEqual(len(self.commits), 2)

        release.set()
        self.assertEqual(await processing, 1)

    async def test_process_once_respects_batch_size(self) -> None:
        first = await self._queue(key=WorkflowKey.COMPANY_RESEARCH, suffix="a")
        second = await self._queue(
            key=WorkflowKey.MARKET_CONTEXT,
            suffix="b",
            owner_id="user-2",
        )
        third = await self._queue(
            key=WorkflowKey.REVIEW_ONLY,
            suffix="c",
            owner_id="user-3",
        )
        finished = await self.worker.process_once()
        self.assertEqual(finished, 2)
        remaining = await self.repository.list_queued(limit=10)
        remaining_ids = {item[0] for item in remaining}
        self.assertNotIn(first, remaining_ids)
        self.assertNotIn(second, remaining_ids)
        self.assertIn(third, remaining_ids)
        finished_again = await self.worker.process_once()
        self.assertEqual(finished_again, 1)

    async def test_run_forever_stops_on_event(self) -> None:
        await self._queue(key=WorkflowKey.COMPANY_RESEARCH, suffix="loop")
        stop_event = asyncio.Event()

        async def stop_soon() -> None:
            await asyncio.sleep(0.05)
            stop_event.set()

        stopper = asyncio.create_task(stop_soon())
        await self.worker.run_forever(interval_seconds=0.2, stop_event=stop_event)
        await stopper
        queued = await self.repository.list_queued(limit=10)
        self.assertEqual(queued, ())

    async def test_run_forever_wakes_before_the_poll_interval(self) -> None:
        wake_event = asyncio.Event()
        stop_event = asyncio.Event()
        self.worker._wake_event = wake_event
        loop = asyncio.create_task(
            self.worker.run_forever(interval_seconds=10, stop_event=stop_event)
        )
        await asyncio.sleep(0.02)

        run_id = await self._queue(
            key=WorkflowKey.COMPANY_RESEARCH,
            suffix="wake",
            input_versions=CONTEXT_INPUT,
        )
        wake_event.set()
        try:
            async with asyncio.timeout(1):
                while True:
                    run = await self.repository.get(run_id)
                    if run is not None and run.status is not WorkflowRunStatus.QUEUED:
                        break
                    await asyncio.sleep(0.01)
        finally:
            stop_event.set()
            wake_event.set()
            await loop

    async def test_list_queued_orders_by_requested_at_fifo(self) -> None:
        first = await self._queue(key=WorkflowKey.COMPANY_RESEARCH, suffix="first")
        second = await self._queue(
            key=WorkflowKey.MARKET_CONTEXT,
            suffix="second",
            owner_id="user-2",
        )
        ordered = await self.repository.list_queued(limit=10)
        self.assertEqual([item[0] for item in ordered], [first, second])

    async def test_runtime_failure_is_persisted_as_failed_not_fake_completed(
        self,
    ) -> None:
        self.runtime = _Runtime(fail=True)
        run_id = await self._queue(
            key=WorkflowKey.COMPANY_RESEARCH,
            suffix="runtime-failure",
            input_versions=CONTEXT_INPUT,
        )

        finished = await self.worker.process_once()

        self.assertEqual(finished, 1)
        run = await self.repository.get(run_id)
        assert run is not None
        self.assertEqual(run.status, WorkflowRunStatus.FAILED)
        self.assertFalse(run.final_artifact)
        self.assertTrue(
            all(item["object_type"] == "MarketSnapshot" for item in self.recorded)
        )
        self.assertTrue(
            any("multi-agent runtime failed" in item for item in run.errors)
        )

    async def test_unconnected_deterministic_service_fails_explicitly(self) -> None:
        run_id = await self._queue(
            key=WorkflowKey.TRADE_PLAN_GENERATION,
            suffix="service-failure",
        )

        finished = await self.worker.process_once()

        self.assertEqual(finished, 1)
        run = await self.repository.get(run_id)
        assert run is not None
        self.assertEqual(run.status, WorkflowRunStatus.FAILED)
        self.assertFalse(run.final_artifact)
        self.assertFalse(self.recorded)
        self.assertTrue(
            any("deterministic service is not connected" in item for item in run.errors)
        )


class TaskPlanFactoryBindingTest(unittest.IsolatedAsyncioTestCase):
    """Worker plan binding must match formal factory owner/input versions."""

    async def test_formal_plan_binds_owner_and_inputs(self) -> None:
        catalog = AgentGovernanceCatalog()
        registry = FormalWorkflowRegistry.build_default(catalog)
        plan = TaskPlanFactory(catalog, registry).formal(
            plan_id="worker-binding",
            owner_id="user-9",
            workflow_key=WorkflowKey.COMPANY_RESEARCH,
            input_versions=INPUT,
            route_reason="binding",
        )
        self.assertEqual(plan.owner_id, "user-9")
        self.assertEqual(plan.input_versions, INPUT)
        self.assertEqual(plan.workflow_key, WorkflowKey.COMPANY_RESEARCH)


if __name__ == "__main__":
    unittest.main()
