from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import datetime
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from finance_god.domain import ConcurrentCommandConflict, DomainInvariantViolation
from finance_god.execution.contracts import SimulationFill, StoredDraft, StoredOrder

from .simulation_models import (
    SimulationDraftRow,
    SimulationExecutionAuditRow,
    SimulationExecutionEventRow,
    SimulationExecutionOutboxRow,
    SimulationFillRow,
    SimulationOrderRow,
)

_HASH = re.compile(r"^[0-9a-f]{64}$")


class SimulationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._lock = asyncio.Lock()

    async def create_draft(
        self,
        draft: StoredDraft,
        *,
        idempotency_key: str,
        request_hash: str,
    ) -> StoredDraft:
        async with self._lock:
            _require_hash(request_hash)
            prior = await self._session.scalar(
                select(SimulationDraftRow).where(
                    SimulationDraftRow.owner_id == draft.owner_id,
                    SimulationDraftRow.idempotency_key == idempotency_key,
                )
            )
            if prior is not None:
                _require_same_hash(prior.request_hash, request_hash)
                return StoredDraft.model_validate(prior.payload_json)
            row = SimulationDraftRow(
                draft_id=draft.draft.draft_id,
                owner_id=draft.owner_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                revision=draft.record_revision,
                status=draft.draft.status.value,
                payload_json=draft.model_dump(
                    mode="json", exclude_computed_fields=True
                ),
                created_at=draft.draft.audit_reference.recorded_at,
                updated_at=draft.draft.audit_reference.recorded_at,
            )
            self._session.add(row)
            await self._session.flush()
            await self._append_bundle(
                "draft",
                draft.draft.draft_id,
                draft.record_revision,
                "draft_created",
                draft.model_dump(mode="json", exclude_computed_fields=True),
                draft.owner_id,
                draft.draft.audit_reference.recorded_at,
            )
            await self._session.flush()
            return draft

    async def get_draft(self, draft_id: str) -> StoredDraft | None:
        row = await self._session.get(SimulationDraftRow, draft_id)
        return StoredDraft.model_validate(row.payload_json) if row else None

    async def save_draft(
        self,
        draft: StoredDraft,
        *,
        expected_revision: int,
    ) -> None:
        async with self._lock:
            if draft.record_revision != expected_revision + 1:
                raise DomainInvariantViolation("draft record revision must advance by one")
            result = await self._session.execute(
                update(SimulationDraftRow)
                .where(
                    SimulationDraftRow.draft_id == draft.draft.draft_id,
                    SimulationDraftRow.revision == expected_revision,
                )
                .values(
                    revision=draft.record_revision,
                    status=draft.draft.status.value,
                    payload_json=draft.model_dump(
                        mode="json", exclude_computed_fields=True
                    ),
                    updated_at=draft.draft.audit_reference.recorded_at,
                )
            )
            _require_cas(result, "draft revision changed")
            await self._append_bundle(
                "draft",
                draft.draft.draft_id,
                draft.record_revision,
                "draft_revised",
                draft.model_dump(mode="json", exclude_computed_fields=True),
                draft.owner_id,
                draft.draft.audit_reference.recorded_at,
            )
            await self._session.flush()

    async def create_order(
        self,
        order: StoredOrder,
        *,
        idempotency_key: str,
        request_hash: str,
    ) -> StoredOrder:
        async with self._lock:
            _require_hash(request_hash)
            prior = await self._session.scalar(
                select(SimulationOrderRow).where(
                    SimulationOrderRow.owner_id == order.owner_id,
                    SimulationOrderRow.idempotency_key == idempotency_key,
                )
            )
            if prior is not None:
                _require_same_hash(prior.request_hash, request_hash)
                return StoredOrder.model_validate(prior.payload_json)
            domain_order = order.exchange_order or order.fund_order
            assert domain_order is not None
            row = SimulationOrderRow(
                order_id=domain_order.order_id,
                draft_id=order.draft_reference.object_id,
                owner_id=order.owner_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                order_kind="exchange" if order.exchange_order else "fund",
                revision=domain_order.revision,
                status=domain_order.status.value,
                payload_json=order.model_dump(
                    mode="json", exclude_computed_fields=True
                ),
                created_at=domain_order.audit_reference.recorded_at,
                updated_at=domain_order.audit_reference.recorded_at,
            )
            self._session.add(row)
            await self._session.flush()
            await self._append_bundle(
                "order",
                domain_order.order_id,
                domain_order.revision,
                "order_submitting",
                order.model_dump(mode="json", exclude_computed_fields=True),
                order.owner_id,
                domain_order.audit_reference.recorded_at,
            )
            await self._session.flush()
            return order

    async def get_order(self, order_id: str) -> StoredOrder | None:
        row = await self._session.get(SimulationOrderRow, order_id)
        return StoredOrder.model_validate(row.payload_json) if row else None

    async def get_order_for_draft(self, draft_id: str) -> StoredOrder | None:
        row = await self._session.scalar(
            select(SimulationOrderRow).where(SimulationOrderRow.draft_id == draft_id)
        )
        return StoredOrder.model_validate(row.payload_json) if row else None

    async def save_order(
        self,
        order: StoredOrder,
        *,
        expected_revision: int,
    ) -> None:
        async with self._lock:
            domain_order = order.exchange_order or order.fund_order
            assert domain_order is not None
            if domain_order.revision != expected_revision + 1:
                raise DomainInvariantViolation("order revision must advance by one")
            result = await self._session.execute(
                update(SimulationOrderRow)
                .where(
                    SimulationOrderRow.order_id == domain_order.order_id,
                    SimulationOrderRow.revision == expected_revision,
                )
                .values(
                    revision=domain_order.revision,
                    status=domain_order.status.value,
                    payload_json=order.model_dump(
                        mode="json", exclude_computed_fields=True
                    ),
                    updated_at=domain_order.audit_reference.recorded_at,
                )
            )
            _require_cas(result, "order revision changed")
            await self._append_bundle(
                "order",
                domain_order.order_id,
                domain_order.revision,
                f"order_{domain_order.status.value}",
                order.model_dump(mode="json", exclude_computed_fields=True),
                order.owner_id,
                domain_order.audit_reference.recorded_at,
            )
            await self._session.flush()

    async def append_fill(self, fill: SimulationFill) -> None:
        async with self._lock:
            self._session.add(
                SimulationFillRow(
                    fill_id=fill.fill_id,
                    order_id=fill.order_id,
                    ledger_fill_id=fill.ledger_fill_id,
                    payload_json=fill.model_dump(
                        mode="json", exclude_computed_fields=True
                    ),
                    occurred_at=fill.occurred_at,
                )
            )
            await self._session.flush()

    async def list_fills(
        self,
        order_id: str | None = None,
    ) -> tuple[SimulationFill, ...]:
        statement = select(SimulationFillRow).order_by(SimulationFillRow.occurred_at)
        if order_id is not None:
            statement = statement.where(SimulationFillRow.order_id == order_id)
        rows = (await self._session.scalars(statement)).all()
        return tuple(SimulationFill.model_validate(row.payload_json) for row in rows)

    async def list_orders(self, owner_id: str) -> tuple[StoredOrder, ...]:
        rows = (
            await self._session.scalars(
                select(SimulationOrderRow)
                .where(SimulationOrderRow.owner_id == owner_id)
                .order_by(SimulationOrderRow.created_at)
            )
        ).all()
        return tuple(StoredOrder.model_validate(row.payload_json) for row in rows)

    async def _append_bundle(
        self,
        aggregate_type: str,
        aggregate_id: str,
        sequence: int,
        event_type: str,
        payload: dict[str, Any],
        actor_id: str,
        occurred_at: datetime,
    ) -> None:
        previous = await self._session.scalar(
            select(SimulationExecutionEventRow)
            .where(
                SimulationExecutionEventRow.aggregate_type == aggregate_type,
                SimulationExecutionEventRow.aggregate_id == aggregate_id,
            )
            .order_by(SimulationExecutionEventRow.sequence.desc())
            .limit(1)
        )
        previous_hash = previous.event_hash if previous else None
        event_hash = _digest(
            {
                "aggregate_type": aggregate_type,
                "aggregate_id": aggregate_id,
                "sequence": sequence,
                "event_type": event_type,
                "previous_hash": previous_hash,
                "payload": payload,
            }
        )
        event_id = f"simulation_event_{event_hash[:32]}"
        self._session.add(
            SimulationExecutionEventRow(
                event_id=event_id,
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                sequence=sequence,
                event_type=event_type,
                previous_hash=previous_hash,
                event_hash=event_hash,
                payload_json=payload,
                occurred_at=occurred_at,
            )
        )
        await self._session.flush()
        self._session.add(
            SimulationExecutionAuditRow(
                audit_id=f"simulation_audit_{event_hash[:32]}",
                aggregate_id=aggregate_id,
                event_id=event_id,
                action=event_type,
                actor_id=actor_id,
                event_hash=event_hash,
                occurred_at=occurred_at,
            )
        )
        self._session.add(
            SimulationExecutionOutboxRow(
                message_id=f"simulation_outbox_{event_hash[:32]}",
                event_id=event_id,
                topic=f"simulation.execution.{event_type}",
                aggregate_id=aggregate_id,
                event_hash=event_hash,
                payload_json=payload,
                occurred_at=occurred_at,
                published_at=None,
            )
        )


def _require_hash(value: str) -> None:
    if not _HASH.fullmatch(value):
        raise ValueError("request_hash must be lowercase SHA-256")


def _require_same_hash(stored: str, requested: str) -> None:
    if stored != requested:
        raise DomainInvariantViolation(
            "idempotency key was already used with a different request"
        )


def _require_cas(result: object, message: str) -> None:
    if cast(CursorResult[Any], result).rowcount != 1:
        raise ConcurrentCommandConflict(message)


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
