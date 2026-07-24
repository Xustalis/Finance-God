from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from finance_god.domain.errors import ConcurrentCommandConflict
from finance_god.trading.access import AuthorizationLimits
from finance_god.trading.mandate import InvestmentMandate

from .mandate_models import InvestmentMandateRow


class MandateRepository:
    """Append-only version store for a single owner's trading authorization."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_current(self, owner_user_id: str) -> InvestmentMandate | None:
        row = await self._session.scalar(
            select(InvestmentMandateRow)
            .where(InvestmentMandateRow.owner_user_id == owner_user_id)
            .order_by(InvestmentMandateRow.version.desc())
            .limit(1)
        )
        return _mandate(row) if row is not None else None

    async def list_versions(self, owner_user_id: str) -> list[InvestmentMandate]:
        rows = await self._session.scalars(
            select(InvestmentMandateRow)
            .where(InvestmentMandateRow.owner_user_id == owner_user_id)
            .order_by(InvestmentMandateRow.version.desc())
        )
        return [_mandate(row) for row in rows]

    async def max_version(self, owner_user_id: str) -> int:
        value = await self._session.scalar(
            select(func.max(InvestmentMandateRow.version)).where(
                InvestmentMandateRow.owner_user_id == owner_user_id
            )
        )
        return int(value or 0)

    async def insert_version(self, mandate: InvestmentMandate) -> InvestmentMandate:
        try:
            self._session.add(InvestmentMandateRow(**_values(mandate)))
            await self._session.flush()
        except IntegrityError as error:
            raise ConcurrentCommandConflict(
                "investment mandate version already exists"
            ) from error
        return mandate


def _values(mandate: InvestmentMandate) -> dict[str, object]:
    return {
        "mandate_id": mandate.mandate_id,
        "owner_user_id": mandate.owner_user_id,
        "version": mandate.version,
        "status": mandate.status.value,
        "autonomy_level": mandate.autonomy_level.value,
        "allowed_markets": list(mandate.allowed_markets),
        "allowed_assets": list(mandate.allowed_assets),
        "allowed_sides": list(mandate.allowed_sides),
        "allowed_order_types": list(mandate.allowed_order_types),
        "short_markets": list(mandate.short_markets),
        "limits_json": mandate.limits.model_dump(mode="json"),
        "valid_from": mandate.valid_from,
        "valid_until": mandate.valid_until,
        "created_at": mandate.created_at,
        "created_by": mandate.created_by,
        "note": mandate.note,
    }


def _mandate(row: InvestmentMandateRow) -> InvestmentMandate:
    return InvestmentMandate.model_validate(
        {
            "mandate_id": row.mandate_id,
            "owner_user_id": row.owner_user_id,
            "version": row.version,
            "status": row.status,
            "autonomy_level": row.autonomy_level,
            "allowed_markets": tuple(row.allowed_markets),
            "allowed_assets": tuple(row.allowed_assets),
            "allowed_sides": tuple(row.allowed_sides),
            "allowed_order_types": tuple(row.allowed_order_types),
            "short_markets": tuple(row.short_markets),
            "limits": AuthorizationLimits.model_validate(row.limits_json),
            "valid_from": row.valid_from,
            "valid_until": row.valid_until,
            "created_at": row.created_at,
            "created_by": row.created_by,
            "note": row.note,
        }
    )
