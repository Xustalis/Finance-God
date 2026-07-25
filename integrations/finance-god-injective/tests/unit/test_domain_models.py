from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from bridge.domain import (
    PLAN_TTL_SECONDS,
    InjectiveOrder,
    InjectivePlan,
    InvalidTransitionError,
    OrderEvent,
    OrderStatus,
    PlanExpiredError,
    PlanStatus,
    RevisionConflictError,
    RiskCheck,
    RiskCode,
    RiskReport,
    Side,
    SourceSnapshot,
)

NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


def make_plan(**overrides: object) -> InjectivePlan:
    values: dict[str, object] = {
        "market_id": "0xmarket",
        "ticker": "INJ/USDT",
        "side": Side.BUY,
        "price": "10.00",
        "quantity": "2.0",
        "created_at": NOW,
    }
    values.update(overrides)
    return InjectivePlan(**values)


def make_report(plan: InjectivePlan, *, passed: bool = True) -> RiskReport:
    return RiskReport(
        plan_id=plan.id,
        plan_revision=plan.revision,
        market_id=plan.market_id,
        reviewed_at=NOW + timedelta(seconds=1),
        notional="20.000",
        midpoint="10.00",
        checks=(
            RiskCheck(
                code=RiskCode.MAX_NOTIONAL,
                passed=passed,
                message="notional check",
            ),
        ),
    )


def test_plan_is_frozen_uses_utc_and_has_exact_default_ttl() -> None:
    local_time = datetime(2026, 7, 25, 20, 0, tzinfo=timezone(timedelta(hours=8)))
    plan = make_plan(created_at=local_time)

    assert plan.created_at == NOW
    assert plan.updated_at == NOW
    assert plan.expires_at == NOW + timedelta(seconds=PLAN_TTL_SECONDS)

    with pytest.raises(ValidationError):
        plan.price = Decimal("11")  # type: ignore[misc]


def test_decimal_fields_reject_float_and_serialize_as_json_strings() -> None:
    with pytest.raises(ValidationError, match="decimal values must be supplied"):
        make_plan(price=10.1)

    payload = json.loads(make_plan().model_dump_json())

    assert payload["price"] == "10.00"
    assert payload["quantity"] == "2.0"


def test_plan_review_confirm_and_submit_increment_revision() -> None:
    draft = make_plan()
    reviewed = draft.apply_review(make_report(draft))
    confirmed = reviewed.confirm(
        expected_revision=reviewed.revision,
        at=NOW + timedelta(seconds=2),
    )
    submitted = confirmed.mark_submitted(
        expected_revision=confirmed.revision,
        at=NOW + timedelta(seconds=3),
    )

    assert (draft.revision, reviewed.revision, confirmed.revision, submitted.revision) == (
        1,
        2,
        3,
        4,
    )
    assert submitted.status is PlanStatus.SUBMITTED
    assert submitted.risk_report is not None
    assert submitted.risk_report.passed

    with pytest.raises(InvalidTransitionError):
        submitted.mark_submission_failed(
            expected_revision=submitted.revision,
            at=NOW + timedelta(seconds=4),
        )


def test_failed_review_rejects_plan_and_mismatched_revision_is_rejected() -> None:
    draft = make_plan()
    rejected = draft.apply_review(make_report(draft, passed=False))

    assert rejected.status is PlanStatus.REJECTED
    assert rejected.risk_report is not None
    assert rejected.risk_report.violations == (RiskCode.MAX_NOTIONAL,)

    with pytest.raises(RevisionConflictError):
        draft.confirm(expected_revision=2, at=NOW + timedelta(seconds=1))


def test_expired_plan_cannot_be_confirmed_and_can_be_explicitly_expired() -> None:
    draft = make_plan()
    reviewed = draft.apply_review(make_report(draft))
    after_expiry = NOW + timedelta(seconds=PLAN_TTL_SECONDS)

    with pytest.raises(PlanExpiredError):
        reviewed.confirm(expected_revision=reviewed.revision, at=after_expiry)

    expired = reviewed.expire(
        expected_revision=reviewed.revision,
        at=after_expiry,
    )
    assert expired.status is PlanStatus.EXPIRED

    confirmed = reviewed.confirm(
        expected_revision=reviewed.revision,
        at=after_expiry - timedelta(seconds=1),
    )
    with pytest.raises(PlanExpiredError):
        confirmed.mark_submitted(
            expected_revision=confirmed.revision,
            at=after_expiry,
        )


def test_order_enforces_chain_lifecycle_and_fill_invariants() -> None:
    order = InjectiveOrder(
        plan_id=uuid4(),
        market_id="0xmarket",
        subaccount_id="0xsubaccount",
        quantity="2.0",
        created_at=NOW,
    )
    broadcast = order.transition(
        OrderStatus.BROADCAST,
        expected_revision=1,
        tx_hash="0xtx",
        at=NOW + timedelta(seconds=1),
    )
    opened = broadcast.transition(
        OrderStatus.OPEN,
        expected_revision=2,
        order_hash="0xorder",
        at=NOW + timedelta(seconds=2),
    )
    partial = opened.transition(
        OrderStatus.PARTIALLY_FILLED,
        expected_revision=3,
        filled_quantity="0.5",
        at=NOW + timedelta(seconds=3),
    )
    more_filled = partial.transition(
        OrderStatus.PARTIALLY_FILLED,
        expected_revision=4,
        filled_quantity="1.5",
        at=NOW + timedelta(seconds=4),
    )
    filled = more_filled.transition(
        OrderStatus.FILLED,
        expected_revision=5,
        filled_quantity="2.0",
        at=NOW + timedelta(seconds=5),
    )

    assert order.is_active
    assert partial.is_active
    assert not filled.is_active
    assert filled.revision == 6
    assert filled.tx_hash == "0xtx"
    assert filled.order_hash == "0xorder"

    with pytest.raises(InvalidTransitionError):
        filled.transition(OrderStatus.CANCELLED, expected_revision=6)


def test_unknown_order_remains_active_and_can_reconcile_to_open() -> None:
    order = InjectiveOrder(
        plan_id=uuid4(),
        market_id="0xmarket",
        subaccount_id="0xsubaccount",
        quantity="2",
        created_at=NOW,
    )
    unknown = order.transition(
        OrderStatus.UNKNOWN,
        expected_revision=1,
        at=NOW + timedelta(seconds=1),
    )
    reconciled = unknown.transition(
        OrderStatus.OPEN,
        expected_revision=2,
        tx_hash="0xtx",
        order_hash="0xorder",
        at=NOW + timedelta(seconds=2),
    )

    assert unknown.is_active
    assert reconciled.status is OrderStatus.OPEN

    with pytest.raises(ValidationError, match="filled quantity cannot exceed"):
        InjectiveOrder(
            plan_id=uuid4(),
            market_id="0xmarket",
            subaccount_id="0xsubaccount",
            quantity="2",
            filled_quantity="3",
        )


def test_order_event_canonicalizes_payload_and_verifies_hash() -> None:
    event = OrderEvent.from_payload(
        order_id=uuid4(),
        event_key="block-1:order-1",
        status=OrderStatus.OPEN,
        payload={"z": 1, "a": "value"},
        occurred_at=NOW,
        observed_at=NOW,
    )

    assert event.payload_json == '{"a":"value","z":1}'

    with pytest.raises(ValidationError, match="payload_hash does not match"):
        OrderEvent(
            order_id=event.order_id,
            event_key=event.event_key,
            payload_hash="0" * 64,
            status=event.status,
            payload_json=event.payload_json,
            occurred_at=NOW,
            observed_at=NOW,
        )


def test_source_snapshot_is_permanently_context_only() -> None:
    snapshot = SourceSnapshot(
        plan_id="finance-plan-1",
        plan_version=2,
        plan_status="confirmed",
        draft_id="draft-1",
        draft_confirmed=True,
        normalized_hash="a" * 64,
        created_at=NOW,
    )
    payload = snapshot.model_dump(mode="json")

    assert payload["usage"] == "context_only"
    assert payload["asset_domain"] == "non_executable_asset_domain"
    assert set(payload).isdisjoint({"jwt", "user_profile", "raw_response"})
