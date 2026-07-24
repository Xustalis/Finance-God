from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from finance_god.domain import TradePlanStatus, VersionReference
from finance_god.infrastructure.persistence.trade_plan_uow import TradePlanUnitOfWork


class Clock(Protocol):
    def now(self) -> datetime: ...


class PersistentTradePlanPort:
    """Execution boundary that accepts only an exact confirmed plan version."""

    def __init__(
        self, session_factory: Callable[[], AsyncSession], clock: Clock
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock

    async def require_executable(self, reference: VersionReference) -> None:
        if reference.object_type != "trade_plan":
            raise ValueError("planned draft dependency must be a TradePlan")
        try:
            revision = int(reference.version)
        except ValueError as error:
            raise ValueError("trade plan version must be an integer revision") from error
        async with TradePlanUnitOfWork(self._session_factory) as uow:
            stored = await uow.plans.get_exact(reference.object_id, revision)
        if stored is None:
            raise LookupError("trade plan version not found")
        plan = stored.plan
        if plan.status is not TradePlanStatus.CONFIRMED:
            raise ValueError("trade plan version is not confirmed")
        if plan.invalidated_by_versions:
            raise ValueError("trade plan inputs have changed")
        if self._clock.now() >= plan.expires_at:
            raise ValueError("trade plan version has expired")
