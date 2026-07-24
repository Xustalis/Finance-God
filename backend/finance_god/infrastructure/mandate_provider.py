"""Authorization provider for the simulation risk boundary.

A narrow read adapter over :class:`MandateService` that hands the risk boundary
the owner's current authorization, auto-creating a lenient default on first use
so pre-existing manual order flows are never interrupted.  It intentionally
exposes only the read capability the risk boundary needs, not the write use
cases.
"""

from __future__ import annotations

from finance_god.application.mandate_service import MandateService
from finance_god.trading.mandate import InvestmentMandate


class PersistentAuthorizationProvider:
    """Load the current persisted mandate for an owner (default-creating)."""

    def __init__(self, service: MandateService) -> None:
        self._service = service

    async def ensure_current(self, owner_id: str) -> InvestmentMandate:
        return await self._service.ensure_current(owner_id)
