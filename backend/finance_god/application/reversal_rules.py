from __future__ import annotations

from finance_god.domain import (
    AccountEventEnvelope,
    AccountEventType,
    DomainInvariantViolation,
)
from finance_god.domain.ledger import ReversalPayload

REVERSIBLE_EVENT_TYPES = frozenset(
    {
        AccountEventType.CASH_RESERVED,
        AccountEventType.CASH_RELEASED,
        AccountEventType.BUY_FILL_RECORDED,
        AccountEventType.SELL_FILL_RECORDED,
        AccountEventType.SHORT_FILL_RECORDED,
        AccountEventType.COVER_FILL_RECORDED,
        AccountEventType.FUND_SUBSCRIPTION_CONFIRMED,
        AccountEventType.FUND_REDEMPTION_CONFIRMED,
    }
)


def validate_reversal_request(
    events: tuple[AccountEventEnvelope, ...], target_event_id: str
) -> AccountEventEnvelope:
    reversed_ids = validate_reversal_history(events)
    target = _target(events, target_event_id)
    _require_reversible_target(
        target,
        expected_latest=events[-1] if events else None,
        reversed_ids=reversed_ids,
    )
    return target


def validate_reversal_history(
    events: tuple[AccountEventEnvelope, ...],
) -> frozenset[str]:
    by_id: dict[str, AccountEventEnvelope] = {}
    reversed_ids: set[str] = set()
    previous: AccountEventEnvelope | None = None
    for event in events:
        payload = event.payload
        if isinstance(payload, ReversalPayload):
            target = by_id.get(payload.original_event_id)
            if target is None:
                raise DomainInvariantViolation("reversal target does not exist")
            if target.event_hash != payload.original_event_hash:
                raise DomainInvariantViolation("reversal target hash does not match")
            _require_reversible_target(
                target,
                expected_latest=previous,
                reversed_ids=frozenset(reversed_ids),
            )
            reversed_ids.add(target.event_id)
        by_id[event.event_id] = event
        previous = event
    return frozenset(reversed_ids)


def _target(
    events: tuple[AccountEventEnvelope, ...], target_event_id: str
) -> AccountEventEnvelope:
    for event in events:
        if event.event_id == target_event_id:
            return event
    raise DomainInvariantViolation("reversal target does not exist")


def _require_reversible_target(
    target: AccountEventEnvelope,
    *,
    expected_latest: AccountEventEnvelope | None,
    reversed_ids: frozenset[str],
) -> None:
    if expected_latest is None or target.event_id != expected_latest.event_id:
        raise DomainInvariantViolation(
            "reversal target must be the immediately preceding latest event"
        )
    if target.event_type not in REVERSIBLE_EVENT_TYPES:
        raise DomainInvariantViolation("event type cannot be reversed")
    if target.event_id in reversed_ids:
        raise DomainInvariantViolation("event has already been reversed")
