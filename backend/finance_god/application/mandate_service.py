"""Mandate application service — versioned trading-authorization use cases.

Wraps :class:`MandateUnitOfWork` to implement the T00 authorization behaviours:
read the current version (auto-creating a lenient default on first access so
manual trading is usable out of the box), list history, save a new version on
edit, and flip status (pause / resume / revoke) — each of which appends a new
immutable version rather than mutating history.  It also produces a read-only
impact preview of existing order intents that the current authorization would
now block.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from finance_god.domain.errors import ConcurrentCommandConflict
from finance_god.infrastructure.persistence.mandate_uow import MandateUnitOfWork
from finance_god.trading.access import (
    AuthorizationLimits,
    AuthorizationStatus,
    AutonomyLevel,
    FrozenModel,
)
from finance_god.trading.mandate import (
    MANDATE_VALIDITY,
    AuthorizationDenial,
    InvestmentMandate,
    default_mandate,
    evaluate_order_authorization,
)


class _Clock(Protocol):
    def now(self) -> datetime: ...


class _IdGenerator(Protocol):
    def new_id(self, prefix: str) -> str: ...


class MandateSpec(FrozenModel):
    """The client-editable fields of an authorization version."""

    autonomy_level: AutonomyLevel
    allowed_markets: tuple[str, ...] = Field(min_length=1)
    allowed_assets: tuple[str, ...] = Field(min_length=1)
    allowed_sides: tuple[str, ...] = Field(min_length=1)
    allowed_order_types: tuple[str, ...] = Field(min_length=1)
    short_markets: tuple[str, ...] = ()
    limits: AuthorizationLimits
    valid_until: AwareDatetime
    note: str | None = Field(default=None, max_length=500)


@dataclass(frozen=True)
class OrderIntentProbe:
    """One existing order intent to test against the current authorization."""

    reference: str
    instrument_id: str
    side: str
    order_type: str
    notional: Decimal | None


class ImpactFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str


class ImpactedOrder(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    reference: str
    instrument_id: str
    side: str
    order_type: str
    findings: tuple[ImpactFinding, ...]


class MandateImpact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evaluated: int
    affected: tuple[ImpactedOrder, ...]


class MandateService:
    """Application service for the versioned investment mandate."""

    def __init__(
        self,
        *,
        session_factory,
        clock: _Clock,
        ids: _IdGenerator,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._ids = ids

    async def ensure_current(self, owner_id: str) -> InvestmentMandate:
        """Return the current mandate, creating a default L0 one on first use."""
        async with MandateUnitOfWork(self._session_factory) as uow:
            current = await uow.mandates.get_current(owner_id)
            if current is not None:
                return current
            created = default_mandate(
                mandate_id=self._ids.new_id("mandate"),
                owner_user_id=owner_id,
                now=self._clock.now(),
                actor=owner_id,
            )
            await uow.mandates.insert_version(created)
            await uow.commit()
            return created

    async def history(self, owner_id: str) -> list[InvestmentMandate]:
        await self.ensure_current(owner_id)
        async with MandateUnitOfWork(self._session_factory) as uow:
            return await uow.mandates.list_versions(owner_id)

    async def save_version(
        self, owner_id: str, *, expected_revision: int, spec: MandateSpec
    ) -> InvestmentMandate:
        now = self._clock.now()
        async with MandateUnitOfWork(self._session_factory) as uow:
            current = await self._require_current(uow, owner_id, expected_revision)
            new_version = InvestmentMandate(
                mandate_id=self._ids.new_id("mandate"),
                owner_user_id=owner_id,
                version=current.version + 1,
                status=AuthorizationStatus.ACTIVE,
                autonomy_level=spec.autonomy_level,
                allowed_markets=spec.allowed_markets,
                allowed_assets=spec.allowed_assets,
                allowed_sides=spec.allowed_sides,
                allowed_order_types=spec.allowed_order_types,
                short_markets=spec.short_markets,
                limits=spec.limits,
                valid_from=now,
                valid_until=spec.valid_until,
                created_at=now,
                created_by=owner_id,
                note=spec.note,
            )
            saved = await uow.mandates.insert_version(new_version)
            await uow.commit()
            return saved

    async def set_status(
        self,
        owner_id: str,
        *,
        expected_revision: int,
        status: AuthorizationStatus,
        note: str | None = None,
    ) -> InvestmentMandate:
        now = self._clock.now()
        async with MandateUnitOfWork(self._session_factory) as uow:
            current = await self._require_current(uow, owner_id, expected_revision)
            valid_until = current.valid_until
            valid_from = now if now < valid_until else current.valid_from
            if valid_until <= valid_from:
                valid_until = now + MANDATE_VALIDITY
                valid_from = now
            new_version = current.model_copy(
                update={
                    "mandate_id": self._ids.new_id("mandate"),
                    "version": current.version + 1,
                    "status": status,
                    "valid_from": valid_from,
                    "valid_until": valid_until,
                    "created_at": now,
                    "created_by": owner_id,
                    "note": note if note is not None else current.note,
                }
            )
            saved = await uow.mandates.insert_version(new_version)
            await uow.commit()
            return saved

    async def impact(
        self, owner_id: str, probes: tuple[OrderIntentProbe, ...]
    ) -> MandateImpact:
        current = await self.ensure_current(owner_id)
        now = self._clock.now()
        affected: list[ImpactedOrder] = []
        for probe in probes:
            denials: tuple[AuthorizationDenial, ...] = evaluate_order_authorization(
                current,
                now=now,
                side=probe.side,
                order_type=probe.order_type,
                instrument_id=probe.instrument_id,
                notional=probe.notional,
            )
            if denials:
                affected.append(
                    ImpactedOrder(
                        reference=probe.reference,
                        instrument_id=probe.instrument_id,
                        side=probe.side,
                        order_type=probe.order_type,
                        findings=tuple(
                            ImpactFinding(code=d.code, message=d.message)
                            for d in denials
                        ),
                    )
                )
        return MandateImpact(evaluated=len(probes), affected=tuple(affected))

    async def _require_current(
        self, uow: MandateUnitOfWork, owner_id: str, expected_revision: int
    ) -> InvestmentMandate:
        current = await uow.mandates.get_current(owner_id)
        if current is None:
            raise LookupError("investment mandate not found")
        if expected_revision != current.version:
            raise ConcurrentCommandConflict(
                "investment mandate has changed since it was loaded"
            )
        return current
