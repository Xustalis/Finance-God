from __future__ import annotations

import asyncio
import hashlib
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url

from finance_god.domain import (
    AuditReference,
    ConcurrentCommandConflict,
    DomainInvariantViolation,
    VersionReference,
    WorkflowRun,
    WorkflowRunStatus,
)
from finance_god.agents.contracts import WorkflowKey
from finance_god.infrastructure.persistence.workflow_persistence import (
    WorkflowUnitOfWork,
    create_workflow_session_factory,
)
from tests.workflow_persistence.executor_support import (
    exercise_persisted_executor,
)

BACKEND = Path(__file__).resolve().parents[2]
POSTGRES_URL = os.getenv("FINANCE_GOD_TEST_POSTGRES_URL")
NOW = datetime(2026, 7, 24, 2, 0, tzinfo=timezone.utc)


def test_real_postgres_migration_and_repository_contract() -> None:
    if POSTGRES_URL is None:
        pytest.skip("FINANCE_GOD_TEST_POSTGRES_URL is not configured")
    database = make_url(POSTGRES_URL).database or ""
    if "test" not in database.lower():
        raise RuntimeError("workflow PostgreSQL contract requires a test database")

    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", POSTGRES_URL)
    asyncio.run(_clear_workflow_rows(POSTGRES_URL))
    command.downgrade(config, "20260724_0003")
    command.upgrade(config, "head")
    command.check(config)
    try:
        asyncio.run(_exercise_postgres_contract(POSTGRES_URL))
    finally:
        asyncio.run(_clear_workflow_rows(POSTGRES_URL))


def test_real_postgres_executor_parallel_and_typed_fact_contract() -> None:
    if POSTGRES_URL is None:
        pytest.skip("FINANCE_GOD_TEST_POSTGRES_URL is not configured")
    database = make_url(POSTGRES_URL).database or ""
    if "test" not in database.lower():
        raise RuntimeError("workflow PostgreSQL contract requires a test database")
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", POSTGRES_URL)
    asyncio.run(_clear_workflow_rows(POSTGRES_URL))
    command.upgrade(config, "head")
    try:
        asyncio.run(_exercise_postgres_executor(POSTGRES_URL))
    finally:
        asyncio.run(_clear_workflow_rows(POSTGRES_URL))


async def _exercise_postgres_executor(database_url: str) -> None:
    engine, factory = create_workflow_session_factory(database_url)
    try:
        completed, runner, events, audits = await exercise_persisted_executor(
            factory,
            suffix="pg-parallel",
            workflow_key=WorkflowKey.COMPANY_RESEARCH,
            parallel_agent_layer=True,
        )
        assert completed.run.status is WorkflowRunStatus.COMPLETED
        assert runner.maximum_parallel >= 2
        assert len(audits) > 0
        assert (events[1].prior_status, events[1].status) == (
            WorkflowRunStatus.QUEUED.value,
            WorkflowRunStatus.RUNNING.value,
        )

        failed, _, _, _ = await exercise_persisted_executor(
            factory,
            suffix="pg-fact-reject",
            workflow_key=WorkflowKey.SIMULATION_EXECUTION,
            invalid_results={"simulation.ledger_update": "rejected"},
        )
        assert failed.run.status is WorkflowRunStatus.FAILED
        assert failed.run.trade_eligible is False
    finally:
        await engine.dispose()


async def _exercise_postgres_contract(database_url: str) -> None:
    engine, factory = create_workflow_session_factory(database_url)
    try:
        async def create(run_id: str, audit_id: str) -> WorkflowRun:
            async with WorkflowUnitOfWork(factory) as uow:
                run = _queued(run_id, audit_id)
                result, _created = await uow.workflows.create_queued(
                    run=run,
                    idempotency_key="pg-idempotency",
                    request_hash=_digest("same-request"),
                    request_intent="PostgreSQL workflow contract",
                    owner_id="pg-user",
                    scope={"operation": "workflow.create"},
                    requested_at=NOW,
                    audit_payload=_audit_payload(audit_id),
                    outbox_payload={"source": "postgres-contract"},
                )
                await uow.commit()
                return result

        first, replay = await asyncio.gather(
            create("pg-run-a", "pg-audit-a"),
            create("pg-run-b", "pg-audit-b"),
        )
        assert first == replay

        with pytest.raises(DomainInvariantViolation, match="different request"):
            async with WorkflowUnitOfWork(factory) as uow:
                await uow.workflows.create_queued(
                    run=_queued("pg-conflict", "pg-conflict-audit"),
                    idempotency_key="pg-idempotency",
                    request_hash=_digest("different-request"),
                    request_intent="PostgreSQL workflow contract",
                    owner_id="pg-user",
                    scope={"operation": "workflow.create"},
                    requested_at=NOW,
                    audit_payload=_audit_payload("pg-conflict-audit"),
                    outbox_payload={"source": "postgres-contract"},
                )

        running = first.transition(
            WorkflowRunStatus.RUNNING,
            audit_reference=AuditReference(
                audit_id="pg-running",
                actor_id="pg-user",
                recorded_at=NOW + timedelta(seconds=10),
            ),
        )
        async with WorkflowUnitOfWork(factory) as uow:
            await uow.workflows.compare_and_append(
                run=running,
                expected_revision=1,
                event_type="workflow_started",
                event_payload=_audit_payload("pg-running"),
                outbox_topic="workflow.started",
            )
            await uow.workflows.append_audit(
                audit_id="pg-execution-audit",
                run_id=first.run_id,
                event_type="node_attempt_failed",
                payload_json={"node_id": "node-1", "failure": "timeout"},
                occurred_at=NOW + timedelta(seconds=11),
            )
            await asyncio.gather(
                *(
                    uow.workflows.append_audit(
                        audit_id=f"pg-layer-audit-{index}",
                        run_id=first.run_id,
                        event_type="node_completed",
                        payload_json={"node_id": f"node-{index}"},
                        occurred_at=NOW + timedelta(seconds=11 + index),
                    )
                    for index in range(1, 4)
                )
            )
            await uow.commit()

        stale = first.transition(
            WorkflowRunStatus.RUNNING,
            audit_reference=AuditReference(
                audit_id="pg-stale",
                actor_id="pg-user",
                recorded_at=NOW + timedelta(seconds=12),
            ),
        )
        with pytest.raises(ConcurrentCommandConflict, match="revision changed"):
            async with WorkflowUnitOfWork(factory) as uow:
                await uow.workflows.compare_and_append(
                    run=stale,
                    expected_revision=1,
                    event_type="workflow_started",
                    event_payload=_audit_payload("pg-stale"),
                    outbox_topic="workflow.started",
                )

        async with WorkflowUnitOfWork(factory) as uow:
            stored = await uow.workflows.get(first.run_id)
            events = await uow.workflows.list_events(first.run_id)
            audits = await uow.workflows.list_audits(first.run_id)
            execution = await uow.workflows.list_execution_audits(first.run_id)
            outbox = await uow.workflows.list_outbox(first.run_id)
            await uow.commit()

        assert stored == running
        assert len(events) == len(audits) == len(outbox) == 2
        assert len(execution) == 4
        assert events[1].previous_event_hash == events[0].event_hash
        assert [
            (event.prior_status, event.status)
            for event in events
        ] == [
            (None, WorkflowRunStatus.QUEUED.value),
            (WorkflowRunStatus.QUEUED.value, WorkflowRunStatus.RUNNING.value),
        ]
        assert all(
            event.event_hash == audit.event_hash == message.event_hash
            for event, audit, message in zip(events, audits, outbox)
        )
    finally:
        await engine.dispose()


async def _clear_workflow_rows(database_url: str) -> None:
    engine, _ = create_workflow_session_factory(database_url)
    try:
        async with engine.begin() as connection:
            exists = await connection.scalar(
                text("SELECT to_regclass('public.workflow_runs')")
            )
            if exists is not None:
                await connection.execute(
                    text(
                        "TRUNCATE TABLE workflow_outbox_messages, "
                        "workflow_execution_audit_records, "
                        "workflow_audit_records, workflow_events, "
                        "workflow_runs CASCADE"
                    )
                )
    finally:
        await engine.dispose()


def _queued(run_id: str, audit_id: str) -> WorkflowRun:
    return WorkflowRun(
        run_id=run_id,
        revision=1,
        workflow_key="company_research",
        workflow_version="1",
        status=WorkflowRunStatus.QUEUED,
        trade_eligible=False,
        input_versions=(
            VersionReference(
                object_type="market_snapshot",
                object_id="pg-snapshot",
                version="1",
            ),
        ),
        final_artifact=None,
        evidence_references=(),
        node_contribution_references=(),
        completed_node_artifacts=(),
        errors=(),
        permissions=("market_data:read",),
        block_reason=None,
        cancellation_reason=None,
        audit_reference=AuditReference(
            audit_id=audit_id,
            actor_id="pg-user",
            recorded_at=NOW + timedelta(seconds=1),
        ),
    )


def _audit_payload(reference: str) -> dict[str, object]:
    return {
        "correlation_id": f"correlation-{reference}",
        "causation_id": f"causation-{reference}",
    }


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
