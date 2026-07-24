from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from finance_god.domain import (
    AuditReference,
    RiskCheckResult,
    RiskCheckStatus,
    RiskReason,
    RiskSeverity,
    VersionReference,
)
from finance_god.infrastructure.simulation_wiring import (
    SimulationRiskAdapter,
    UuidIdGenerator,
)


class _Clock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


def _soft_risk(now: datetime) -> RiskCheckResult:
    order = VersionReference(
        object_type="order_draft",
        object_id="draft-1",
        version="1",
    )
    return RiskCheckResult(
        risk_check_id="risk-1",
        revision=1,
        status=RiskCheckStatus.CONFIRMATION_REQUIRED,
        order_version=order,
        rule_version=VersionReference(
            object_type="risk_rules",
            object_id="simulation-risk-v1",
            version="1",
        ),
        reasons=(
            RiskReason(
                code="concentration_warning",
                severity=RiskSeverity.SOFT,
                message="single position concentration requires confirmation",
            ),
        ),
        checked_at=now,
        expires_at=now + timedelta(minutes=30),
        input_versions=(order,),
        audit_reference=AuditReference(
            audit_id="audit-risk-1",
            actor_id="simulation-risk-adapter",
            recorded_at=now,
        ),
    )


@pytest.mark.asyncio
async def test_simulation_soft_risk_confirmation_uses_server_reason_hash() -> None:
    now = datetime(2026, 7, 24, 8, tzinfo=UTC)
    result = _soft_risk(now)
    adapter = SimulationRiskAdapter(_Clock(now + timedelta(seconds=1)), UuidIdGenerator())

    confirmed = await adapter.confirm_soft(
        owner_id="owner-1",
        result=result,
        seen_reason_hash=result.reason_hash,
    )

    assert confirmed.soft_confirmation is not None
    assert confirmed.soft_confirmation.actor_id == "owner-1"
    assert confirmed.reason_hash == result.reason_hash


@pytest.mark.asyncio
async def test_simulation_soft_risk_rejects_changed_reason_hash() -> None:
    now = datetime(2026, 7, 24, 8, tzinfo=UTC)
    result = _soft_risk(now)
    adapter = SimulationRiskAdapter(_Clock(now + timedelta(seconds=1)), UuidIdGenerator())

    with pytest.raises(ValueError, match="risk reason summary changed"):
        await adapter.confirm_soft(
            owner_id="owner-1",
            result=result,
            seen_reason_hash="0" * 64,
        )
