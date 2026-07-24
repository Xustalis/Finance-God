from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from finance_god.domain import (
    AuditReference,
    OrderDraft,
    OrderDraftStatus,
    OrderSide,
    OrderType,
    RiskCheckStatus,
    RiskSeverity,
    TimeInForce,
    VersionReference,
)
from finance_god.execution import DraftMode, StoredDraft
from finance_god.infrastructure.simulation_wiring import (
    SimulationRiskAdapter,
    UuidIdGenerator,
)
from finance_god.trading.access import AuthorizationStatus, AutonomyLevel
from finance_god.trading.mandate import DEFAULT_LIMITS, InvestmentMandate

NOW = datetime(2026, 7, 24, 8, tzinfo=UTC)


class _Clock:
    def now(self) -> datetime:
        return NOW


class _Authorization:
    def __init__(self, mandate: InvestmentMandate) -> None:
        self._mandate = mandate

    async def ensure_current(self, owner_id: str) -> InvestmentMandate:
        del owner_id
        return self._mandate


class _MutableClock:
    def __init__(self) -> None:
        self.current = NOW

    def now(self) -> datetime:
        return self.current


class _FirstUseAuthorization:
    def __init__(self, clock: _MutableClock) -> None:
        self._clock = clock

    async def ensure_current(self, owner_id: str) -> InvestmentMandate:
        self._clock.current += timedelta(microseconds=1)
        return _mandate(
            owner_user_id=owner_id,
            valid_from=self._clock.current,
            created_at=self._clock.current,
        )


def _mandate(**overrides: object) -> InvestmentMandate:
    base = dict(
        mandate_id="mandate-1",
        owner_user_id="owner-1",
        version=1,
        status=AuthorizationStatus.ACTIVE,
        autonomy_level=AutonomyLevel.L0,
        allowed_markets=("CN",),
        allowed_assets=("stock",),
        allowed_sides=("buy",),
        allowed_order_types=("limit",),
        short_markets=(),
        limits=DEFAULT_LIMITS,
        valid_from=NOW,
        valid_until=NOW + timedelta(days=30),
        created_at=NOW,
        created_by="owner-1",
        note=None,
    )
    base.update(overrides)
    return InvestmentMandate(**base)  # type: ignore[arg-type]


def _draft(**overrides: object) -> StoredDraft:
    order_kwargs = dict(
        draft_id="draft-1",
        revision=1,
        status=OrderDraftStatus.DRAFT,
        account_id="account-1",
        instrument_id="600519.SH",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("100"),
        amount=None,
        limit_price=Decimal("10"),
        time_in_force=TimeInForce.DAY,
        fund_rule_version=None,
        valid_until=NOW + timedelta(days=1),
        input_versions=(
            VersionReference(
                object_type="market_snapshot",
                object_id="600519.SH",
                version="snapshot-v1",
            ),
        ),
        audit_reference=AuditReference(
            audit_id="audit-draft-1", actor_id="owner-1", recorded_at=NOW
        ),
    )
    order_kwargs.update(overrides)
    return StoredDraft(
        owner_id="owner-1",
        mode=DraftMode.MANUAL,
        draft=OrderDraft(**order_kwargs),  # type: ignore[arg-type]
        plan_reference=None,
    )


def _adapter(mandate: InvestmentMandate | None) -> SimulationRiskAdapter:
    authorization = _Authorization(mandate) if mandate is not None else None
    return SimulationRiskAdapter(_Clock(), UuidIdGenerator(), authorization)


@pytest.mark.asyncio
async def test_risk_passes_within_authorized_scope() -> None:
    result = await _adapter(_mandate()).evaluate(_draft())
    assert result.status is RiskCheckStatus.PASSED
    assert result.reasons == ()


@pytest.mark.asyncio
async def test_risk_evaluation_time_follows_first_use_authorization_creation() -> None:
    clock = _MutableClock()
    adapter = SimulationRiskAdapter(
        clock,
        UuidIdGenerator(),
        _FirstUseAuthorization(clock),
    )

    result = await adapter.evaluate(_draft())

    assert result.status is RiskCheckStatus.PASSED
    assert result.checked_at == clock.current


@pytest.mark.asyncio
async def test_risk_blocks_unauthorized_side_with_hard_reason() -> None:
    result = await _adapter(_mandate(allowed_sides=("sell",))).evaluate(_draft())
    assert result.status is RiskCheckStatus.BLOCKED
    assert [r.code for r in result.reasons] == ["side_not_authorized"]
    assert all(r.severity is RiskSeverity.HARD for r in result.reasons)


@pytest.mark.asyncio
async def test_risk_blocks_inactive_mandate() -> None:
    result = await _adapter(
        _mandate(status=AuthorizationStatus.REVOKED)
    ).evaluate(_draft())
    assert result.status is RiskCheckStatus.BLOCKED
    assert [r.code for r in result.reasons] == ["mandate_inactive"]


@pytest.mark.asyncio
async def test_risk_blocks_single_order_limit() -> None:
    tight = _mandate(
        limits=DEFAULT_LIMITS.model_copy(
            update={"max_single_order_amount": Decimal("500")}
        )
    )
    result = await _adapter(tight).evaluate(_draft())
    assert result.status is RiskCheckStatus.BLOCKED
    assert [r.code for r in result.reasons] == ["single_order_limit_exceeded"]


@pytest.mark.asyncio
async def test_risk_passes_without_authorization_provider() -> None:
    result = await _adapter(None).evaluate(_draft())
    assert result.status is RiskCheckStatus.PASSED
