from __future__ import annotations

import json
import re
from collections.abc import Collection, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.persistence.locks import wallet_advisory_lock
from bridge.persistence.models import (
    ACTIVE_ORDER_STATUSES,
    IDEMPOTENCY_STATUSES,
    ORDER_STATUSES,
    PLAN_STATUSES,
    BroadcastAttemptModel,
    IdempotencyRecordModel,
    InjectiveOrderModel,
    InjectivePlanModel,
    OrderEventModel,
    SourceSnapshotModel,
    new_id,
    utc_now,
)

SOURCE_PROJECTION_FIELDS = frozenset(
    {
        "plan_id",
        "draft_id",
        "version",
        "status",
        "expires_at",
        "audit_reference",
        "draft_status",
        "draft_confirmed",
    }
)
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")

ORDER_TRANSITIONS: dict[str, frozenset[str]] = {
    "broadcasting": frozenset({"broadcast", "rejected", "unknown"}),
    "broadcast": frozenset(
        {"open", "partially_filled", "filled", "cancelled", "rejected", "unknown"}
    ),
    "open": frozenset({"partially_filled", "filled", "cancelled", "unknown"}),
    "partially_filled": frozenset({"partially_filled", "filled", "cancelled", "unknown"}),
    "unknown": frozenset(
        {"broadcast", "open", "partially_filled", "filled", "cancelled", "rejected"}
    ),
    "filled": frozenset(),
    "cancelled": frozenset(),
    "rejected": frozenset(),
}


class PersistenceError(RuntimeError):
    pass


class RecordNotFoundError(PersistenceError):
    pass


class RevisionConflictError(PersistenceError):
    pass


class InvalidStateTransitionError(PersistenceError):
    pass


class PlanExpiredError(PersistenceError):
    pass


class ActiveOrderLimitError(PersistenceError):
    pass


class IdempotencyConflictError(PersistenceError):
    pass


class DuplicateOrderError(PersistenceError):
    pass


def canonical_json_hash(value: Mapping[str, Any]) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(serialized.encode("utf-8")).hexdigest()


def _validate_sha256(value: str, *, field_name: str) -> str:
    normalized = value.strip().lower()
    if not HASH_PATTERN.fullmatch(normalized):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")
    return normalized


def _controlled_projection(
    projection: Mapping[str, Any],
    *,
    allowed_fields: Collection[str],
) -> dict[str, Any]:
    unexpected = set(projection).difference(allowed_fields)
    if unexpected:
        names = ", ".join(sorted(unexpected))
        raise ValueError(f"projection contains fields that are not allowlisted: {names}")
    result = dict(projection)
    canonical_json_hash(result)
    return result


class BridgeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_source_snapshot(
        self,
        *,
        source_plan_id: str,
        projection: Mapping[str, Any],
        source_draft_id: str | None = None,
        source_plan_version: str | None = None,
        source_plan_status: str | None = None,
        source_expires_at: datetime | None = None,
        audit_reference: str | None = None,
        draft_status: str | None = None,
        draft_confirmed: bool | None = None,
        snapshot_id: str | None = None,
    ) -> SourceSnapshotModel:
        controlled = _controlled_projection(
            projection,
            allowed_fields=SOURCE_PROJECTION_FIELDS,
        )
        normalized_hash = canonical_json_hash(controlled)
        existing = await self.find_source_snapshot_by_hash(normalized_hash)
        if existing is not None:
            return existing

        snapshot = SourceSnapshotModel(
            id=snapshot_id or new_id(),
            source_plan_id=source_plan_id,
            source_draft_id=source_draft_id,
            source_plan_version=source_plan_version,
            source_plan_status=source_plan_status,
            source_expires_at=source_expires_at,
            audit_reference=audit_reference,
            draft_status=draft_status,
            draft_confirmed=draft_confirmed,
            classification="context_only",
            asset_domain="non_executable_asset_domain",
            normalized_hash=normalized_hash,
            projection=controlled,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(snapshot)
                await self._session.flush()
        except IntegrityError:
            concurrent = await self.find_source_snapshot_by_hash(normalized_hash)
            if concurrent is None:
                raise
            return concurrent
        return snapshot

    async def find_source_snapshot(self, snapshot_id: str) -> SourceSnapshotModel | None:
        return await self._session.get(SourceSnapshotModel, snapshot_id)

    async def get_source_snapshot(self, snapshot_id: str) -> SourceSnapshotModel:
        snapshot = await self.find_source_snapshot(snapshot_id)
        if snapshot is None:
            raise RecordNotFoundError(f"source snapshot {snapshot_id!r} does not exist")
        return snapshot

    async def find_source_snapshot_by_hash(
        self,
        normalized_hash: str,
    ) -> SourceSnapshotModel | None:
        statement = select(SourceSnapshotModel).where(
            SourceSnapshotModel.normalized_hash == normalized_hash
        )
        return await self._session.scalar(statement)

    async def create_plan(
        self,
        *,
        market_id: str,
        ticker: str,
        side: str,
        price: Decimal,
        quantity: Decimal,
        expires_at: datetime,
        source_snapshot_id: str | None = None,
        plan_id: str | None = None,
    ) -> InjectivePlanModel:
        normalized_side = side.strip().lower()
        if normalized_side not in {"buy", "sell"}:
            raise ValueError("side must be 'buy' or 'sell'")
        if price <= 0 or quantity <= 0:
            raise ValueError("price and quantity must be positive")
        if source_snapshot_id is not None:
            await self.get_source_snapshot(source_snapshot_id)

        plan = InjectivePlanModel(
            id=plan_id or new_id(),
            market_id=market_id,
            ticker=ticker,
            source_snapshot_id=source_snapshot_id,
            side=normalized_side,
            order_type="limit",
            time_in_force="gtc",
            price=price,
            quantity=quantity,
            status="draft",
            revision=1,
            expires_at=expires_at,
        )
        self._session.add(plan)
        await self._session.flush()
        return plan

    async def find_plan(
        self,
        plan_id: str,
        *,
        for_update: bool = False,
    ) -> InjectivePlanModel | None:
        statement = select(InjectivePlanModel).where(InjectivePlanModel.id == plan_id)
        if for_update:
            statement = statement.with_for_update()
        return await self._session.scalar(statement)

    async def get_plan(
        self,
        plan_id: str,
        *,
        for_update: bool = False,
    ) -> InjectivePlanModel:
        plan = await self.find_plan(plan_id, for_update=for_update)
        if plan is None:
            raise RecordNotFoundError(f"plan {plan_id!r} does not exist")
        return plan

    async def list_plans_by_status(
        self,
        status: str,
        *,
        limit: int = 100,
    ) -> list[InjectivePlanModel]:
        if status not in PLAN_STATUSES:
            raise ValueError(f"unknown plan status {status!r}")
        if limit < 1:
            raise ValueError("limit must be positive")
        statement = (
            select(InjectivePlanModel)
            .where(InjectivePlanModel.status == status)
            .order_by(InjectivePlanModel.created_at, InjectivePlanModel.id)
            .limit(limit)
        )
        return list((await self._session.scalars(statement)).all())

    async def list_confirmed_plans(
        self,
        *,
        limit: int = 100,
    ) -> list[InjectivePlanModel]:
        """Return plans awaiting serialized signing/broadcast."""
        return await self.list_plans_by_status("confirmed", limit=limit)

    async def review_plan(
        self,
        plan_id: str,
        *,
        expected_revision: int,
        risk_report: Mapping[str, Any],
        approved: bool,
        rejection_reason: str | None = None,
        reviewed_at: datetime | None = None,
    ) -> InjectivePlanModel:
        controlled_report = dict(risk_report)
        canonical_json_hash(controlled_report)
        target_status = "reviewed" if approved else "rejected"
        return await self._compare_and_swap_plan(
            plan_id,
            expected_revision=expected_revision,
            expected_statuses={"draft"},
            target_status=target_status,
            risk_report=controlled_report,
            rejection_reason=None if approved else rejection_reason,
            reviewed_at=reviewed_at or utc_now(),
        )

    async def confirm_plan(
        self,
        plan_id: str,
        *,
        expected_revision: int,
        confirmed_at: datetime | None = None,
    ) -> InjectivePlanModel:
        now = confirmed_at or utc_now()
        plan = await self.get_plan(plan_id)
        if _as_utc(plan.expires_at) <= _as_utc(now):
            raise PlanExpiredError(f"plan {plan_id!r} expired before confirmation")
        return await self._compare_and_swap_plan(
            plan_id,
            expected_revision=expected_revision,
            expected_statuses={"reviewed"},
            target_status="confirmed",
            confirmed_at=now,
        )

    async def expire_plan(
        self,
        plan_id: str,
        *,
        expected_revision: int,
        now: datetime | None = None,
    ) -> InjectivePlanModel:
        checked_at = now or utc_now()
        plan = await self.get_plan(plan_id)
        if _as_utc(plan.expires_at) > _as_utc(checked_at):
            raise InvalidStateTransitionError(f"plan {plan_id!r} has not expired")
        return await self._compare_and_swap_plan(
            plan_id,
            expected_revision=expected_revision,
            expected_statuses={"draft", "reviewed", "confirmed"},
            target_status="expired",
        )

    async def begin_broadcast(
        self,
        plan_id: str,
        *,
        expected_revision: int,
        market_id: str,
        subaccount_id: str,
        request_hash: str,
        max_active_orders: int,
        allow_sqlite_test_noop: bool = False,
    ) -> tuple[InjectiveOrderModel, BroadcastAttemptModel]:
        digest = _validate_sha256(request_hash, field_name="request_hash")
        if max_active_orders < 1:
            raise ValueError("max_active_orders must be at least 1")

        async with wallet_advisory_lock(
            self._session,
            subaccount_id,
            allow_sqlite_test_noop=allow_sqlite_test_noop,
        ):
            active_count = await self.count_active_orders(subaccount_id=subaccount_id)
            if active_count >= max_active_orders:
                raise ActiveOrderLimitError(
                    f"subaccount {subaccount_id!r} already has {active_count} active order(s)"
                )

            plan = await self.get_plan(plan_id)
            if _as_utc(plan.expires_at) <= utc_now():
                raise PlanExpiredError(f"plan {plan_id!r} expired before broadcast")
            claimed = await self._compare_and_swap_plan(
                plan_id,
                expected_revision=expected_revision,
                expected_statuses={"confirmed"},
                target_status="confirmed",
            )
            if await self.find_order_by_plan(plan_id) is not None:
                raise DuplicateOrderError(f"plan {plan_id!r} already has an execution order")
            if claimed.market_id != market_id:
                raise InvalidStateTransitionError(
                    f"plan {plan_id!r} is bound to market {claimed.market_id!r}, not {market_id!r}"
                )

            order_id = new_id()
            order = InjectiveOrderModel(
                id=order_id,
                plan_id=claimed.id,
                market_id=market_id,
                subaccount_id=subaccount_id,
                client_order_id=order_id,
                status="broadcasting",
                quantity=claimed.quantity,
                filled_quantity=Decimal("0"),
                revision=1,
            )
            self._session.add(order)
            await self._session.flush()
            attempt = BroadcastAttemptModel(
                plan_id=claimed.id,
                order_id=order.id,
                attempt_no=1,
                request_hash=digest,
                status="started",
            )
            self._session.add(attempt)
            await self._session.flush()
            return order, attempt

    async def complete_broadcast(
        self,
        order_id: str,
        *,
        tx_hash: str,
        order_hash: str | None = None,
        chain_projection: Mapping[str, Any] | None = None,
        completed_at: datetime | None = None,
    ) -> InjectiveOrderModel:
        now = completed_at or utc_now()
        order = await self.get_order(order_id, for_update=True)
        if order.status != "broadcasting":
            raise InvalidStateTransitionError(
                f"order {order_id!r} cannot complete broadcast from {order.status!r}"
            )
        attempt = await self._get_started_attempt(order_id)
        plan = await self.get_plan(order.plan_id, for_update=True)
        if plan.status != "confirmed":
            raise InvalidStateTransitionError(
                f"plan {plan.id!r} cannot be submitted from {plan.status!r}"
            )

        controlled_projection = None
        if chain_projection is not None:
            controlled_projection = dict(chain_projection)
            canonical_json_hash(controlled_projection)

        order.status = "broadcast"
        order.tx_hash = tx_hash
        order.order_hash = order_hash
        order.chain_projection = controlled_projection
        order.revision += 1
        order.updated_at = now
        attempt.status = "broadcast"
        attempt.tx_hash = tx_hash
        attempt.completed_at = now
        plan.status = "submitted"
        plan.revision += 1
        plan.submitted_at = now
        plan.updated_at = now
        await self._session.flush()
        return order

    async def fail_broadcast(
        self,
        order_id: str,
        *,
        error_code: str,
        error_message: str,
        indeterminate: bool,
        tx_hash: str | None = None,
        completed_at: datetime | None = None,
    ) -> InjectiveOrderModel:
        now = completed_at or utc_now()
        order = await self.get_order(order_id, for_update=True)
        if order.status != "broadcasting":
            raise InvalidStateTransitionError(
                f"order {order_id!r} cannot fail broadcast from {order.status!r}"
            )
        attempt = await self._get_started_attempt(order_id)
        plan = await self.get_plan(order.plan_id, for_update=True)
        if plan.status != "confirmed":
            raise InvalidStateTransitionError(
                f"plan {plan.id!r} cannot fail submission from {plan.status!r}"
            )

        order.status = "unknown" if indeterminate else "rejected"
        order.tx_hash = tx_hash
        order.revision += 1
        order.updated_at = now
        attempt.status = "unknown" if indeterminate else "failed"
        attempt.tx_hash = tx_hash
        attempt.error_code = error_code
        attempt.error_message = error_message
        attempt.completed_at = now
        plan.status = "submission_failed"
        plan.revision += 1
        plan.rejection_reason = error_code
        plan.updated_at = now
        await self._session.flush()
        return order

    async def find_order(
        self,
        order_id: str,
        *,
        for_update: bool = False,
    ) -> InjectiveOrderModel | None:
        statement = select(InjectiveOrderModel).where(InjectiveOrderModel.id == order_id)
        if for_update:
            statement = statement.with_for_update()
        return await self._session.scalar(statement)

    async def get_order(
        self,
        order_id: str,
        *,
        for_update: bool = False,
    ) -> InjectiveOrderModel:
        order = await self.find_order(order_id, for_update=for_update)
        if order is None:
            raise RecordNotFoundError(f"order {order_id!r} does not exist")
        return order

    async def find_order_by_plan(self, plan_id: str) -> InjectiveOrderModel | None:
        statement = select(InjectiveOrderModel).where(InjectiveOrderModel.plan_id == plan_id)
        return await self._session.scalar(statement)

    async def count_active_orders(self, *, subaccount_id: str | None = None) -> int:
        statement = (
            select(func.count())
            .select_from(InjectiveOrderModel)
            .where(InjectiveOrderModel.status.in_(ACTIVE_ORDER_STATUSES))
        )
        if subaccount_id is not None:
            statement = statement.where(InjectiveOrderModel.subaccount_id == subaccount_id)
        return int((await self._session.scalar(statement)) or 0)

    async def list_active_orders(
        self,
        *,
        limit: int = 100,
        subaccount_id: str | None = None,
    ) -> list[InjectiveOrderModel]:
        if limit < 1:
            raise ValueError("limit must be positive")
        statement = (
            select(InjectiveOrderModel)
            .where(InjectiveOrderModel.status.in_(ACTIVE_ORDER_STATUSES))
            .order_by(InjectiveOrderModel.updated_at, InjectiveOrderModel.id)
            .limit(limit)
        )
        if subaccount_id is not None:
            statement = statement.where(InjectiveOrderModel.subaccount_id == subaccount_id)
        return list((await self._session.scalars(statement)).all())

    async def apply_order_event(
        self,
        order_id: str,
        *,
        event_key: str,
        status: str,
        payload: Mapping[str, Any],
        occurred_at: datetime,
        filled_quantity: Decimal | None = None,
        tx_hash: str | None = None,
        order_hash: str | None = None,
    ) -> tuple[InjectiveOrderModel, OrderEventModel, bool]:
        if status not in ORDER_STATUSES:
            raise ValueError(f"unknown order status {status!r}")
        controlled_payload = dict(payload)
        payload_hash = canonical_json_hash(controlled_payload)
        existing = await self.find_order_event(
            event_key=event_key,
            payload_hash=payload_hash,
        )
        if existing is not None:
            return await self.get_order(order_id), existing, False

        order = await self.get_order(order_id, for_update=True)
        if status != order.status and status not in ORDER_TRANSITIONS[order.status]:
            raise InvalidStateTransitionError(
                f"order {order_id!r} cannot transition from {order.status!r} to {status!r}"
            )
        if filled_quantity is not None:
            if filled_quantity < order.filled_quantity:
                raise InvalidStateTransitionError("filled quantity cannot decrease")
            if filled_quantity > order.quantity:
                raise InvalidStateTransitionError("filled quantity cannot exceed order quantity")

        event = OrderEventModel(
            order_id=order_id,
            event_key=event_key,
            payload_hash=payload_hash,
            status=status,
            payload_json=controlled_payload,
            occurred_at=occurred_at,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(event)
                await self._session.flush()
        except IntegrityError:
            concurrent = await self.find_order_event(
                event_key=event_key,
                payload_hash=payload_hash,
            )
            if concurrent is None:
                raise
            return order, concurrent, False

        order.status = status
        if filled_quantity is not None:
            order.filled_quantity = filled_quantity
        if tx_hash is not None:
            order.tx_hash = tx_hash
        if order_hash is not None:
            order.order_hash = order_hash
        order.last_chain_timestamp = occurred_at
        order.chain_projection = controlled_payload
        order.revision += 1
        order.updated_at = utc_now()
        await self._session.flush()
        return order, event, True

    async def find_order_event(
        self,
        *,
        event_key: str,
        payload_hash: str,
    ) -> OrderEventModel | None:
        statement = select(OrderEventModel).where(
            OrderEventModel.event_key == event_key,
            OrderEventModel.payload_hash == payload_hash,
        )
        return await self._session.scalar(statement)

    async def reserve_idempotency(
        self,
        *,
        operation: str,
        idempotency_key: str,
        request_hash: str,
    ) -> tuple[IdempotencyRecordModel, bool]:
        digest = _validate_sha256(request_hash, field_name="request_hash")
        if not operation.strip() or not idempotency_key.strip():
            raise ValueError("operation and idempotency_key cannot be blank")
        existing = await self.find_idempotency(operation, idempotency_key)
        if existing is not None:
            self._assert_matching_request_hash(existing, digest)
            return existing, False

        record = IdempotencyRecordModel(
            operation=operation,
            idempotency_key=idempotency_key,
            request_hash=digest,
            status="in_progress",
        )
        try:
            async with self._session.begin_nested():
                self._session.add(record)
                await self._session.flush()
        except IntegrityError:
            concurrent = await self.find_idempotency(operation, idempotency_key)
            if concurrent is None:
                raise
            self._assert_matching_request_hash(concurrent, digest)
            return concurrent, False
        return record, True

    async def find_idempotency(
        self,
        operation: str,
        idempotency_key: str,
    ) -> IdempotencyRecordModel | None:
        statement = select(IdempotencyRecordModel).where(
            IdempotencyRecordModel.operation == operation,
            IdempotencyRecordModel.idempotency_key == idempotency_key,
        )
        return await self._session.scalar(statement)

    async def complete_idempotency(
        self,
        record_id: str,
        *,
        response_code: int,
        response_body: Mapping[str, Any],
        resource_type: str | None = None,
        resource_id: str | None = None,
    ) -> IdempotencyRecordModel:
        return await self._finish_idempotency(
            record_id,
            status="completed",
            response_code=response_code,
            response_body=response_body,
            resource_type=resource_type,
            resource_id=resource_id,
        )

    async def fail_idempotency(
        self,
        record_id: str,
        *,
        response_code: int,
        response_body: Mapping[str, Any],
    ) -> IdempotencyRecordModel:
        return await self._finish_idempotency(
            record_id,
            status="failed",
            response_code=response_code,
            response_body=response_body,
        )

    async def _finish_idempotency(
        self,
        record_id: str,
        *,
        status: str,
        response_code: int,
        response_body: Mapping[str, Any],
        resource_type: str | None = None,
        resource_id: str | None = None,
    ) -> IdempotencyRecordModel:
        if status not in IDEMPOTENCY_STATUSES:
            raise ValueError(f"unknown idempotency status {status!r}")
        body = dict(response_body)
        canonical_json_hash(body)
        record = await self._session.get(
            IdempotencyRecordModel,
            record_id,
            with_for_update=True,
        )
        if record is None:
            raise RecordNotFoundError(f"idempotency record {record_id!r} does not exist")
        if record.status != "in_progress":
            raise InvalidStateTransitionError(
                f"idempotency record {record_id!r} is already {record.status!r}"
            )
        record.status = status
        record.response_code = response_code
        record.response_body = body
        record.resource_type = resource_type
        record.resource_id = resource_id
        record.updated_at = utc_now()
        await self._session.flush()
        return record

    async def _compare_and_swap_plan(
        self,
        plan_id: str,
        *,
        expected_revision: int,
        expected_statuses: Collection[str],
        target_status: str,
        **values: Any,
    ) -> InjectivePlanModel:
        if target_status not in PLAN_STATUSES:
            raise ValueError(f"unknown plan status {target_status!r}")
        invalid_expected = set(expected_statuses).difference(PLAN_STATUSES)
        if invalid_expected:
            raise ValueError(f"unknown expected plan statuses: {sorted(invalid_expected)!r}")
        changed_at = utc_now()
        statement = (
            update(InjectivePlanModel)
            .where(
                InjectivePlanModel.id == plan_id,
                InjectivePlanModel.revision == expected_revision,
                InjectivePlanModel.status.in_(expected_statuses),
            )
            .values(
                status=target_status,
                revision=InjectivePlanModel.revision + 1,
                updated_at=changed_at,
                **values,
            )
            .execution_options(synchronize_session="fetch")
        )
        result = await self._session.execute(statement)
        if result.rowcount == 1:
            return await self.get_plan(plan_id)

        current = await self.find_plan(plan_id)
        if current is None:
            raise RecordNotFoundError(f"plan {plan_id!r} does not exist")
        if current.revision != expected_revision:
            raise RevisionConflictError(
                f"plan {plan_id!r} revision is {current.revision}, expected {expected_revision}"
            )
        raise InvalidStateTransitionError(
            f"plan {plan_id!r} cannot transition from {current.status!r} to {target_status!r}"
        )

    async def _get_started_attempt(self, order_id: str) -> BroadcastAttemptModel:
        statement = select(BroadcastAttemptModel).where(
            BroadcastAttemptModel.order_id == order_id,
            BroadcastAttemptModel.status == "started",
        )
        attempt = await self._session.scalar(statement.with_for_update())
        if attempt is None:
            raise RecordNotFoundError(f"order {order_id!r} has no active broadcast attempt")
        return attempt

    @staticmethod
    def _assert_matching_request_hash(
        record: IdempotencyRecordModel,
        request_hash: str,
    ) -> None:
        if record.request_hash != request_hash:
            raise IdempotencyConflictError(
                "idempotency key was already used with a different request"
            )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
