from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from finance_god.domain import ConcurrentCommandConflict, TradePlan

from .trade_plan_models import TradePlanDraftLinkRow, TradePlanVersionRow


@dataclass(frozen=True, slots=True)
class StoredTradePlan:
    owner_user_id: str
    source_type: str
    source_id: str
    plan: TradePlan
    data_status: dict[str, object]


@dataclass(frozen=True, slots=True)
class TradePlanDraftLink:
    action_id: str
    draft_id: str
    draft_revision: int


class TradePlanRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_latest(
        self, owner_user_id: str, plan_id: str
    ) -> StoredTradePlan | None:
        row = await self._session.scalar(
            select(TradePlanVersionRow)
            .where(
                TradePlanVersionRow.owner_user_id == owner_user_id,
                TradePlanVersionRow.plan_id == plan_id,
            )
            .order_by(TradePlanVersionRow.revision.desc())
            .limit(1)
        )
        return _stored(row) if row is not None else None

    async def get_exact(
        self, plan_id: str, revision: int
    ) -> StoredTradePlan | None:
        row = await self._session.get(TradePlanVersionRow, (plan_id, revision))
        return _stored(row) if row is not None else None

    async def get_by_creation_key(
        self, owner_user_id: str, creation_key: str
    ) -> StoredTradePlan | None:
        row = await self._session.scalar(
            select(TradePlanVersionRow).where(
                TradePlanVersionRow.owner_user_id == owner_user_id,
                TradePlanVersionRow.creation_key == creation_key,
            )
        )
        return _stored(row) if row is not None else None

    async def history(
        self, owner_user_id: str, plan_id: str
    ) -> list[StoredTradePlan]:
        rows = await self._session.scalars(
            select(TradePlanVersionRow)
            .where(
                TradePlanVersionRow.owner_user_id == owner_user_id,
                TradePlanVersionRow.plan_id == plan_id,
            )
            .order_by(TradePlanVersionRow.revision.desc())
        )
        return [_stored(row) for row in rows]

    async def insert(
        self,
        stored: StoredTradePlan,
        *,
        creation_key: str | None = None,
    ) -> StoredTradePlan:
        plan = stored.plan
        try:
            self._session.add(
                TradePlanVersionRow(
                    plan_id=plan.plan_id,
                    revision=plan.revision,
                    owner_user_id=stored.owner_user_id,
                    account_id=plan.account_id,
                    status=plan.status.value,
                    source_type=stored.source_type,
                    source_id=stored.source_id,
                    creation_key=creation_key,
                    plan_json=plan.model_dump(mode="json"),
                    data_status_json=stored.data_status,
                    created_at=plan.audit_reference.recorded_at,
                )
            )
            await self._session.flush()
        except IntegrityError as error:
            raise ConcurrentCommandConflict(
                "trade plan version or idempotency key already exists"
            ) from error
        return stored

    async def add_draft_link(
        self,
        *,
        plan_id: str,
        plan_revision: int,
        action_id: str,
        draft_id: str,
        draft_revision: int,
        created_at: datetime,
    ) -> None:
        existing = await self._session.scalar(
            select(TradePlanDraftLinkRow).where(
                TradePlanDraftLinkRow.plan_id == plan_id,
                TradePlanDraftLinkRow.plan_revision == plan_revision,
                TradePlanDraftLinkRow.action_id == action_id,
            )
        )
        if existing is not None:
            if existing.draft_id != draft_id:
                raise ConcurrentCommandConflict(
                    "trade plan action is already linked to another draft"
                )
            return
        self._session.add(
            TradePlanDraftLinkRow(
                plan_id=plan_id,
                plan_revision=plan_revision,
                action_id=action_id,
                draft_id=draft_id,
                draft_revision=draft_revision,
                created_at=created_at,
            )
        )
        await self._session.flush()

    async def list_draft_links(
        self, plan_id: str, plan_revision: int
    ) -> tuple[TradePlanDraftLink, ...]:
        rows = await self._session.scalars(
            select(TradePlanDraftLinkRow)
            .where(
                TradePlanDraftLinkRow.plan_id == plan_id,
                TradePlanDraftLinkRow.plan_revision == plan_revision,
            )
            .order_by(TradePlanDraftLinkRow.id)
        )
        return tuple(
            TradePlanDraftLink(
                action_id=row.action_id,
                draft_id=row.draft_id,
                draft_revision=row.draft_revision,
            )
            for row in rows
        )


def _stored(row: TradePlanVersionRow) -> StoredTradePlan:
    return StoredTradePlan(
        owner_user_id=row.owner_user_id,
        source_type=row.source_type,
        source_id=row.source_id,
        plan=TradePlan.model_validate(row.plan_json),
        data_status=dict(row.data_status_json),
    )
