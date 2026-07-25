#!/usr/bin/env python3
"""Daemon entrypoint for the Workflow Worker.

Runs forever until interrupted (SIGINT/SIGTERM), claiming queued WorkflowRuns
and driving each to a terminal status. Intended as a standalone long-lived
process so it can eventually leave the API lifespan without changing the claim
loop.

Usage:
    python -m scripts.run_workflow_worker            # run continuously
    python -m scripts.run_workflow_worker --once     # single cycle (smoke)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal

from sqlalchemy import select

from app.config import settings
from app.db.session import create_db_session
from app.models.profile import DirectionRecommendation, InvestmentProfile
from finance_god.api.desk_routes import project_suitability_profile
from finance_god.application.candidate_service import (
    CandidateScoringService,
    candidates_for_profile,
)
from finance_god.application.evidence_service import EvidenceService
from finance_god.application.ledger_service import SimulationLedgerService
from finance_god.application.mandate_service import MandateService
from finance_god.application.portfolio_query import PortfolioQueryService
from finance_god.application.trade_plan_service import TradePlanService
from finance_god.application.workflow_worker import WorkflowWorker
from finance_god.crawler.service import get_crawler_service
from finance_god.domain.simulation_rules import SIMULATION_RULE_VERSION
from finance_god.infrastructure.mandate_provider import PersistentAuthorizationProvider
from finance_god.infrastructure.persistence.uow import SqlAlchemyUnitOfWork
from finance_god.infrastructure.persistence.workflow_uow import WorkflowUnitOfWork
from finance_god.infrastructure.persistence.workspace_uow import WorkspaceUnitOfWork
from finance_god.infrastructure.simulation_wiring import (
    SystemClock,
    UuidIdGenerator,
    build_simulation_services,
)
from finance_god.market_data import MarketDataApplication, MarketDataService
from finance_god.orchestration.multi_agent import MultiAgentRuntime
from finance_god.orchestration.workflow_runtime import (
    create_workflow_command_runtime_from_environment,
)

_LOGGER = logging.getLogger("finance_god.workflow.worker")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--once",
        action="store_true",
        help="process one batch and exit",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=None,
        help="override seconds between poll cycles",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="override max queued runs claimed per cycle",
    )
    args = parser.parse_args()
    if args.interval is not None and args.interval <= 0:
        parser.error("--interval must be greater than 0")
    if args.batch_size is not None and args.batch_size < 1:
        parser.error("--batch-size must be at least 1")
    return args


async def _run(args: argparse.Namespace) -> None:
    runtime = create_workflow_command_runtime_from_environment(
        database_url=settings.database_url
    )
    session_factory = runtime.session_factory
    batch_size = args.batch_size or settings.workflow_worker_batch_size
    interval = args.interval or settings.workflow_worker_interval_seconds

    def uow_factory() -> WorkflowUnitOfWork:
        return WorkflowUnitOfWork(session_factory)

    try:
        agent_runtime = MultiAgentRuntime.from_environment(
            enable_panda_data=True,
            enable_finrobot_metrics=False,
        )
    except Exception:
        _LOGGER.warning("PandaData Agent runtime unavailable; using evidence-only runtime")
        agent_runtime = MultiAgentRuntime.from_environment(
            enable_panda_data=False,
            enable_finrobot_metrics=False,
        )

    async def runtime_provider() -> MultiAgentRuntime:
        return agent_runtime

    evidence = EvidenceService(
        session_factory=create_db_session,
        clock=SystemClock(),
        ids=UuidIdGenerator(),
    )
    market_service = MarketDataService.from_environment()
    market = MarketDataApplication(market_service)
    portfolio = PortfolioQueryService(
        uow_factory=lambda: SqlAlchemyUnitOfWork(create_db_session),
        clock=SystemClock(),
        rule_version=SIMULATION_RULE_VERSION,
    )
    candidates = CandidateScoringService(
        portfolio=portfolio,
        quotes_provider=market.quotes,
        rule_version=SIMULATION_RULE_VERSION,
    )
    clock = SystemClock()
    ids = UuidIdGenerator()

    class _StaticRuleCatalog:
        simulation_rule_version = SIMULATION_RULE_VERSION

    ledger = SimulationLedgerService(
        uow_factory=lambda: SqlAlchemyUnitOfWork(create_db_session),
        clock=clock,
        ids=ids,
        rules=_StaticRuleCatalog(),
    )
    mandate = MandateService(
        session_factory=create_db_session,
        clock=clock,
        ids=ids,
    )
    execution, _accounts = build_simulation_services(
        uow_factory=lambda: SqlAlchemyUnitOfWork(create_db_session),
        simulation_session_factory=create_db_session,
        ledger=ledger,
        market_data=market_service,
        authorization=PersistentAuthorizationProvider(mandate),
    )
    trade_plans = TradePlanService(
        session_factory=create_db_session,
        clock=clock,
        ids=ids,
        candidates=candidates,
        portfolio=portfolio,
        quotes_provider=market.quotes,
        drafts=execution,
    )

    async def profile_provider(owner_id: str) -> dict | None:
        async with create_db_session() as session:
            profile = await session.scalar(
                select(InvestmentProfile)
                .where(InvestmentProfile.user_id == owner_id)
                .order_by(InvestmentProfile.version.desc())
            )
            if profile is None:
                return None
            recommendations = (
                await session.scalars(
                    select(DirectionRecommendation)
                    .where(DirectionRecommendation.profile_id == profile.id)
                    .order_by(DirectionRecommendation.rank)
                )
            ).all()
        selected = next(
            (item.direction for item in recommendations if item.selected),
            None,
        )
        raw = {
            "version": profile.version,
            "archetype_code": profile.archetype_code,
            "archetype_title": profile.archetype_title,
            "risk_level": profile.risk_level,
            "loss_tolerance_percent": profile.loss_tolerance_percent,
            "confidence": profile.confidence,
            "completeness": profile.completeness,
            "education_only": profile.education_only,
            "recommended_directions": [
                item.direction for item in recommendations
            ],
            **({"selected_direction": selected} if selected else {}),
        }
        projection = project_suitability_profile(raw)
        return projection.model_dump(mode="json") if projection.available else None

    async def candidate_provider(owner_id: str, now, profile: dict | None):
        async with WorkspaceUnitOfWork(create_db_session) as uow:
            ignores = await uow.candidate_ignores.list(owner_id)
        return await candidates_for_profile(
            service=candidates,
            owner_id=owner_id,
            now=now,
            profile=profile,
            ignored={item.instrument_id: item.reason for item in ignores},
        )

    async def portfolio_provider(owner_id: str):
        return await portfolio.positions(owner_id=owner_id)

    async def trade_plan_provider(
        owner_id: str,
        symbol: str,
        idempotency_key: str,
    ):
        return await trade_plans.create_from_candidate(
            owner_id=owner_id,
            instrument_id=symbol,
            idempotency_key=idempotency_key,
        )

    async def order_draft_provider(owner_id: str, draft_id: str):
        return await execution.get_draft(owner_id=owner_id, draft_id=draft_id)

    async def order_draft_review_provider(
        owner_id: str,
        draft_id: str,
        expected_revision: int,
    ):
        return await execution.review(
            owner_id=owner_id,
            draft_id=draft_id,
            expected_revision=expected_revision,
        )

    async def record_evidence(
        *,
        owner_id: str,
        subject: str,
        run,
        object_type: str,
        object_id: str,
        version: str,
        content: dict[str, object] | None = None,
        conclusion: str | None = None,
        provider: str = "multi-agent-runtime",
        generated_at=None,
    ) -> None:
        if content is not None:
            await evidence.record(
                owner_id=owner_id,
                object_type=object_type,
                object_id=object_id,
                version=version,
                subject=subject,
                conclusion=conclusion,
                content=content,
                provider=provider,
                generated_at=generated_at,
            )
            return
        if run is None:
            raise ValueError("workflow evidence requires an AgentRun or content")
        await evidence.record_agent_run(
            owner_id=owner_id,
            run=run,
            subject=subject,
            object_type=object_type,
            object_id=object_id,
            version=version,
        )

    worker = WorkflowWorker(
        uow_factory=uow_factory,
        runtime_provider=runtime_provider,
        evidence_recorder=record_evidence,
        profile_provider=profile_provider,
        candidate_provider=candidate_provider,
        market_context_provider=market.quotes,
        market_history_provider=market.historical_daily_bars,
        information_facts_provider=market.information_facts,
        sentiment_facts_provider=market.sentiment_facts,
        crawler_context_provider=lambda: get_crawler_service().get_full_report(
            news_limit=20
        ),
        portfolio_provider=portfolio_provider,
        trade_plan_provider=trade_plan_provider,
        order_draft_provider=order_draft_provider,
        order_draft_review_provider=order_draft_review_provider,
        registry=runtime.registry,
        batch_size=batch_size,
    )
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:  # pragma: no cover - Windows fallback
            pass

    try:
        if args.once:
            finished = await worker.process_once()
            _LOGGER.info("workflow worker once finished %d run(s)", finished)
            return
        _LOGGER.info(
            "starting workflow worker at %.1fs interval (batch=%d)",
            interval,
            batch_size,
        )
        await worker.run_forever(interval_seconds=interval, stop_event=stop_event)
        _LOGGER.info("workflow worker stopped")
    finally:
        await runtime.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = _parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
