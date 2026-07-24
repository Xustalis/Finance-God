from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from finance_god.domain.errors import (
    ConcurrentCommandConflict,
    DomainInvariantViolation,
)
from finance_god.domain.models import (
    AuditReference,
    Notification,
    NotificationPreference,
    NotificationStatus,
    WatchlistGroup,
    WatchlistInstrument,
)

from .workspace_models import (
    NotificationPreferenceRow,
    NotificationReceiptRow,
    NotificationRow,
    WatchlistGroupRow,
    WatchlistInstrumentRow,
)


class WatchlistRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_group(
        self, owner_user_id: str, group_id: str
    ) -> WatchlistGroup | None:
        row = await self._session.scalar(
            select(WatchlistGroupRow).where(
                WatchlistGroupRow.group_id == group_id,
                WatchlistGroupRow.owner_user_id == owner_user_id,
            )
        )
        return _watchlist_group(row) if row is not None else None

    async def create_group(self, group: WatchlistGroup) -> WatchlistGroup:
        try:
            self._session.add(WatchlistGroupRow(**group.model_dump()))
            await self._session.flush()
        except IntegrityError as error:
            raise ConcurrentCommandConflict("watchlist group already exists") from error
        return group

    async def update_group(
        self, group: WatchlistGroup, *, expected_revision: int
    ) -> WatchlistGroup:
        updated_at = datetime.now(UTC)
        result = cast(
            CursorResult[Any],
            await self._session.execute(
                update(WatchlistGroupRow)
                .where(
                    WatchlistGroupRow.group_id == group.group_id,
                    WatchlistGroupRow.owner_user_id == group.owner_user_id,
                    WatchlistGroupRow.revision == expected_revision,
                )
                .values(
                    name=group.name,
                    description=group.description,
                    revision=expected_revision + 1,
                    updated_at=updated_at,
                )
            )
        )
        if result.rowcount != 1:
            raise ConcurrentCommandConflict("watchlist group revision changed")
        return group.model_copy(
            update={"revision": expected_revision + 1, "updated_at": updated_at}
        )

    async def add_instrument(
        self, *, owner_user_id: str, group_id: str, instrument_id: str, added_by: str
    ) -> WatchlistInstrument:
        group = await self.get_group(owner_user_id, group_id)
        if group is None:
            raise DomainInvariantViolation("watchlist group not found")
        instrument = WatchlistInstrument(
            instrument_id=instrument_id,
            group_id=group_id,
            revision=1,
            added_at=datetime.now(UTC),
            added_by=added_by,
        )
        try:
            self._session.add(WatchlistInstrumentRow(**instrument.model_dump()))
            await self._session.flush()
        except IntegrityError as error:
            raise ConcurrentCommandConflict("watchlist instrument already exists") from error
        return instrument

    async def list_groups(self, owner_user_id: str) -> list[WatchlistGroup]:
        rows = await self._session.scalars(
            select(WatchlistGroupRow)
            .where(WatchlistGroupRow.owner_user_id == owner_user_id)
            .order_by(WatchlistGroupRow.created_at, WatchlistGroupRow.group_id)
        )
        return [_watchlist_group(row) for row in rows]


class NotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_notification(self, notification: Notification) -> Notification:
        try:
            self._session.add(NotificationRow(**_notification_values(notification)))
            await self._session.flush()
        except IntegrityError as error:
            raise ConcurrentCommandConflict("notification already exists") from error
        return notification

    async def mark_read(self, owner_user_id: str, notification_id: str) -> None:
        now = datetime.now(UTC)
        result = cast(
            CursorResult[Any],
            await self._session.execute(
                update(NotificationRow)
                .where(
                    NotificationRow.owner_user_id == owner_user_id,
                    NotificationRow.notification_id == notification_id,
                    NotificationRow.status == NotificationStatus.UNREAD.value,
                )
                .values(status=NotificationStatus.READ.value, read_at=now)
            )
        )
        if result.rowcount == 0:
            notification = await self.get(owner_user_id, notification_id)
            if notification is None:
                raise DomainInvariantViolation("notification not found")
            return
        self._session.add(
            NotificationReceiptRow(
                notification_id=notification_id,
                owner_user_id=owner_user_id,
                read_at=now,
                revision=1,
            )
        )
        await self._session.flush()

    async def list_unread(self, owner_user_id: str) -> list[Notification]:
        rows = await self._session.scalars(
            select(NotificationRow)
            .where(
                NotificationRow.owner_user_id == owner_user_id,
                NotificationRow.status == NotificationStatus.UNREAD.value,
            )
            .order_by(NotificationRow.created_at.desc(), NotificationRow.notification_id)
        )
        return [_notification(row) for row in rows]

    async def get(self, owner_user_id: str, notification_id: str) -> Notification | None:
        row = await self._session.scalar(
            select(NotificationRow).where(
                NotificationRow.owner_user_id == owner_user_id,
                NotificationRow.notification_id == notification_id,
            )
        )
        return _notification(row) if row is not None else None


class NotificationPreferenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, owner_user_id: str) -> NotificationPreference | None:
        row = await self._session.get(NotificationPreferenceRow, owner_user_id)
        return _preference(row) if row is not None else None

    async def update(self, preference: NotificationPreference) -> NotificationPreference:
        await self._session.merge(
            NotificationPreferenceRow(
                owner_user_id=preference.owner_user_id,
                preferences_json={
                    category.value: enabled
                    for category, enabled in preference.category_preferences.items()
                },
                updated_at=preference.updated_at,
            )
        )
        await self._session.flush()
        return preference


def _watchlist_group(row: WatchlistGroupRow) -> WatchlistGroup:
    return WatchlistGroup.model_validate(
        {
            "group_id": row.group_id,
            "owner_user_id": row.owner_user_id,
            "name": row.name,
            "description": row.description,
            "revision": row.revision,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
    )


def _notification_values(notification: Notification) -> dict[str, object]:
    return {
        "notification_id": notification.notification_id,
        "owner_user_id": notification.owner_user_id,
        "category": notification.category.value,
        "severity": notification.severity.value,
        "title": notification.title,
        "message": notification.message,
        "source_object_type": notification.source_object_type,
        "source_object_id": notification.source_object_id,
        "source_version": notification.source_version,
        "required": notification.required,
        "status": notification.status.value,
        "created_at": notification.created_at,
        "read_at": notification.read_at,
        "audit_id": notification.audit_reference.audit_id,
        "audit_actor_id": notification.audit_reference.actor_id,
        "audit_recorded_at": notification.audit_reference.recorded_at,
    }


def _notification(row: NotificationRow) -> Notification:
    return Notification.model_validate(
        {
            "notification_id": row.notification_id,
            "owner_user_id": row.owner_user_id,
            "category": row.category,
            "severity": row.severity,
            "title": row.title,
            "message": row.message,
            "source_object_type": row.source_object_type,
            "source_object_id": row.source_object_id,
            "source_version": row.source_version,
            "required": row.required,
            "status": row.status,
            "created_at": row.created_at,
            "read_at": row.read_at,
            "audit_reference": AuditReference(
                audit_id=row.audit_id,
                actor_id=row.audit_actor_id,
                recorded_at=row.audit_recorded_at,
            ),
        }
    )


def _preference(row: NotificationPreferenceRow) -> NotificationPreference:
    return NotificationPreference.model_validate(
        {
            "owner_user_id": row.owner_user_id,
            "category_preferences": row.preferences_json,
            "updated_at": row.updated_at,
        }
    )
