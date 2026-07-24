from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

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
NOW = datetime(2026, 7, 24, 1, 0, tzinfo=timezone.utc)


def request_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def audit(sequence: int) -> AuditReference:
    return AuditReference(
        audit_id=f"audit-{sequence}",
        actor_id="user-1",
        recorded_at=NOW + timedelta(seconds=sequence),
    )


def queued(run_id: str = "run-1") -> WorkflowRun:
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
                object_id="snapshot-1",
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
        audit_reference=audit(1),
    )


def audit_payload(sequence: int) -> dict[str, object]:
    return {
        "correlation_id": f"correlation-{sequence}",
        "causation_id": f"causation-{sequence}",
        "reason": "workflow state persisted",
    }


def outbox_payload(sequence: int) -> dict[str, object]:
    return {"command_sequence": sequence}


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    database = tmp_path / "workflow.db"
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database}")
    command.upgrade(config, "head")
    return f"sqlite+aiosqlite:///{database}"


async def create_run(
    uow: WorkflowUnitOfWork,
    run: WorkflowRun,
    *,
    key: str = "request-1",
    digest: str | None = None,
) -> WorkflowRun:
    persisted, _created = await uow.workflows.create_queued(
        run=run,
        idempotency_key=key,
        request_hash=digest or request_hash("payload-1"),
        request_intent="research ACME",
        owner_id="user-1",
        scope={"operation": "workflow.create"},
        requested_at=NOW,
        audit_payload=audit_payload(1),
        outbox_payload=outbox_payload(1),
    )
    return persisted


def test_create_is_idempotent_and_writes_atomic_facts(database_url: str) -> None:
    asyncio.run(_create_is_idempotent_and_writes_atomic_facts(database_url))


async def _create_is_idempotent_and_writes_atomic_facts(
    database_url: str,
) -> None:
    engine, factory = create_workflow_session_factory(database_url)
    try:
        async with WorkflowUnitOfWork(factory) as uow:
            created = await create_run(uow, queued())
            await uow.commit()

        async with WorkflowUnitOfWork(factory) as uow:
            replayed = await create_run(uow, queued("a-different-proposed-run"))
            events = await uow.workflows.list_events(created.run_id)
            audits = await uow.workflows.list_audits(created.run_id)
            outbox = await uow.workflows.list_outbox(created.run_id)
            await uow.commit()

        assert replayed == created
        assert len(events) == len(audits) == len(outbox) == 1
        assert events[0].event_hash == audits[0].event_hash == outbox[0].event_hash
        assert audits[0].payload_json["reason"] == "workflow state persisted"
        assert outbox[0].payload_json["command_sequence"] == 1
    finally:
        await engine.dispose()


def test_same_scoped_key_with_different_hash_is_explicit_conflict(
    database_url: str,
) -> None:
    asyncio.run(_same_scoped_key_with_different_hash_is_explicit_conflict(database_url))


async def _same_scoped_key_with_different_hash_is_explicit_conflict(
    database_url: str,
) -> None:
    engine, factory = create_workflow_session_factory(database_url)
    try:
        async with WorkflowUnitOfWork(factory) as uow:
            await create_run(uow, queued())
            await uow.commit()

        with pytest.raises(
            DomainInvariantViolation,
            match="different request",
        ):
            async with WorkflowUnitOfWork(factory) as uow:
                await create_run(
                    uow,
                    queued("run-2"),
                    digest=request_hash("different-payload"),
                )
                await uow.commit()
    finally:
        await engine.dispose()


def test_uncommitted_projection_event_audit_and_outbox_roll_back_together(
    database_url: str,
) -> None:
    asyncio.run(_uncommitted_bundle_rolls_back_together(database_url))


async def _uncommitted_bundle_rolls_back_together(database_url: str) -> None:
    engine, factory = create_workflow_session_factory(database_url)
    try:
        async with WorkflowUnitOfWork(factory) as uow:
            await create_run(uow, queued())

        async with WorkflowUnitOfWork(factory) as uow:
            assert await uow.workflows.get("run-1") is None
            assert await uow.workflows.list_events("run-1") == ()
            assert await uow.workflows.list_audits("run-1") == ()
            assert await uow.workflows.list_outbox("run-1") == ()
            await uow.commit()
    finally:
        await engine.dispose()


def test_cas_rejects_stale_writer_and_state_survives_engine_restart(
    database_url: str,
) -> None:
    asyncio.run(_cas_and_restart(database_url))


async def _cas_and_restart(database_url: str) -> None:
    engine, factory = create_workflow_session_factory(database_url)
    try:
        async with WorkflowUnitOfWork(factory) as uow:
            await create_run(uow, queued())
            await uow.commit()

        async with WorkflowUnitOfWork(factory) as uow:
            stale_run = await uow.workflows.get("run-1")
            await uow.commit()
        assert stale_run is not None

        async with WorkflowUnitOfWork(factory) as uow:
            current_run = await uow.workflows.get("run-1")
            assert current_run is not None
            first_running = current_run.transition(
                WorkflowRunStatus.RUNNING,
                audit_reference=audit(2),
            )
            await uow.workflows.compare_and_append(
                run=first_running,
                expected_revision=1,
                event_type="workflow_started",
                event_payload=audit_payload(2),
                outbox_topic="workflow.started",
            )
            await uow.commit()

        stale_running = stale_run.transition(
            WorkflowRunStatus.RUNNING,
            audit_reference=audit(3),
        )
        async with WorkflowUnitOfWork(factory) as uow:
            with pytest.raises(
                ConcurrentCommandConflict,
                match="revision changed",
            ):
                await uow.workflows.compare_and_append(
                    run=stale_running,
                    expected_revision=1,
                    event_type="workflow_started",
                    event_payload=audit_payload(3),
                    outbox_topic="workflow.started",
                )
    finally:
        await engine.dispose()

    restarted_engine, restarted_factory = create_workflow_session_factory(database_url)
    try:
        async with WorkflowUnitOfWork(restarted_factory) as uow:
            persisted = await uow.workflows.get("run-1")
            events = await uow.workflows.list_events("run-1")
            await uow.commit()
        assert persisted == first_running
        assert [event.sequence for event in events] == [1, 2]
        assert events[1].previous_event_hash == events[0].event_hash
        assert [
            (event.prior_status, event.status)
            for event in events
        ] == [
            (None, WorkflowRunStatus.QUEUED.value),
            (WorkflowRunStatus.QUEUED.value, WorkflowRunStatus.RUNNING.value),
        ]
    finally:
        await restarted_engine.dispose()


def test_parallel_layer_compute_then_serial_execution_audit(
    database_url: str,
) -> None:
    asyncio.run(_parallel_layer_compute_then_serial_audit(database_url))


async def _parallel_layer_compute_then_serial_audit(database_url: str) -> None:
    async def compute(node_id: str) -> dict[str, object]:
        await asyncio.sleep(0)
        return {"node_id": node_id, "status": "completed"}

    engine, factory = create_workflow_session_factory(database_url)
    try:
        async with WorkflowUnitOfWork(factory) as uow:
            await create_run(uow, queued())
            await uow.commit()

        outcomes = await asyncio.gather(
            compute("node-a"),
            compute("node-b"),
            compute("node-c"),
        )
        async with WorkflowUnitOfWork(factory) as uow:
            for index, outcome in enumerate(outcomes, start=1):
                await uow.workflows.append_audit(
                    audit_id=f"layer-audit-{index}",
                    run_id="run-1",
                    event_type="node_completed",
                    payload_json=outcome,
                    occurred_at=NOW + timedelta(seconds=index + 1),
                )
            await uow.commit()

        async with WorkflowUnitOfWork(factory) as uow:
            audits = await uow.workflows.list_execution_audits("run-1")
            await uow.commit()
        assert [item.payload_json["node_id"] for item in audits] == [
            "node-a",
            "node-b",
            "node-c",
        ]
    finally:
        await engine.dispose()


def test_repository_serializes_accidental_concurrent_execution_audits(
    database_url: str,
) -> None:
    asyncio.run(_repository_serializes_concurrent_audits(database_url))


async def _repository_serializes_concurrent_audits(database_url: str) -> None:
    engine, factory = create_workflow_session_factory(database_url)
    try:
        async with WorkflowUnitOfWork(factory) as uow:
            await create_run(uow, queued())
            await uow.commit()

        async with WorkflowUnitOfWork(factory) as uow:
            await asyncio.gather(
                *(
                    uow.workflows.append_audit(
                        audit_id=f"concurrent-audit-{index}",
                        run_id="run-1",
                        event_type="node_completed",
                        payload_json={"node_id": f"node-{index}"},
                        occurred_at=NOW + timedelta(seconds=index + 1),
                    )
                    for index in range(1, 4)
                )
            )
            await uow.commit()

        async with WorkflowUnitOfWork(factory) as uow:
            audits = await uow.workflows.list_execution_audits("run-1")
            await uow.commit()
        assert len(audits) == 3
    finally:
        await engine.dispose()


def test_real_sqlite_executor_parallel_layer_and_typed_fact_gate(
    database_url: str,
) -> None:
    asyncio.run(_real_sqlite_executor_contract(database_url))


async def _real_sqlite_executor_contract(database_url: str) -> None:
    engine, factory = create_workflow_session_factory(database_url)
    try:
        completed, runner, events, audits = await exercise_persisted_executor(
            factory,
            suffix="sqlite-parallel",
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
            suffix="sqlite-fact-reject",
            workflow_key=WorkflowKey.SIMULATION_EXECUTION,
            invalid_results={"simulation.match": "rejected"},
        )
        assert failed.run.status is WorkflowRunStatus.FAILED
        assert failed.run.trade_eligible is False
    finally:
        await engine.dispose()


def test_execution_audit_does_not_advance_workflow_revision(
    database_url: str,
) -> None:
    asyncio.run(_execution_audit_does_not_advance_revision(database_url))


async def _execution_audit_does_not_advance_revision(database_url: str) -> None:
    engine, factory = create_workflow_session_factory(database_url)
    try:
        async with WorkflowUnitOfWork(factory) as uow:
            await create_run(uow, queued())
            await uow.workflows.append_audit(
                audit_id="execution-audit-1",
                run_id="run-1",
                event_type="node_attempt_failed",
                payload_json={"node_id": "node-1", "failure": "timeout"},
                occurred_at=NOW + timedelta(seconds=2),
                actor_id="system",
                correlation_id="correlation-2",
            )
            await uow.commit()

        async with WorkflowUnitOfWork(factory) as uow:
            persisted = await uow.workflows.get("run-1")
            execution_audits = await uow.workflows.list_execution_audits("run-1")
            revision_audits = await uow.workflows.list_audits("run-1")
            await uow.commit()
        assert persisted is not None
        assert persisted.revision == 1
        assert len(revision_audits) == 1
        assert len(execution_audits) == 1
        assert execution_audits[0].payload_json["failure"] == "timeout"
    finally:
        await engine.dispose()


def test_workflow_facts_are_database_enforced_append_only(
    database_url: str,
) -> None:
    asyncio.run(_workflow_facts_are_append_only(database_url))


async def _workflow_facts_are_append_only(database_url: str) -> None:
    engine, factory = create_workflow_session_factory(database_url)
    try:
        async with WorkflowUnitOfWork(factory) as uow:
            await create_run(uow, queued())
            await uow.workflows.append_audit(
                audit_id="execution-audit-1",
                run_id="run-1",
                event_type="node_started",
                payload_json={"node_id": "node-1"},
                occurred_at=NOW + timedelta(seconds=2),
            )
            await uow.commit()

        async with engine.begin() as connection:
            event_id = await connection.scalar(
                text("SELECT event_id FROM workflow_events")
            )
            audit_id = await connection.scalar(
                text("SELECT audit_id FROM workflow_audit_records")
            )
            execution_audit_id = await connection.scalar(
                text("SELECT audit_id FROM workflow_execution_audit_records")
            )
        with pytest.raises(IntegrityError, match="append-only workflow fact table"):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE workflow_events SET status = 'failed' "
                        "WHERE event_id = :event_id"
                    ),
                    {"event_id": event_id},
                )
        with pytest.raises(IntegrityError, match="append-only workflow fact table"):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "DELETE FROM workflow_audit_records "
                        "WHERE audit_id = :audit_id"
                    ),
                    {"audit_id": audit_id},
                )
        with pytest.raises(IntegrityError, match="append-only workflow fact table"):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "DELETE FROM workflow_execution_audit_records "
                        "WHERE audit_id = :audit_id"
                    ),
                    {"audit_id": execution_audit_id},
                )
    finally:
        await engine.dispose()
