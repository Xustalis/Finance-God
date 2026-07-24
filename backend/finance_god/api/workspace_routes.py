from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from finance_god.domain.errors import ConcurrentCommandConflict, DomainInvariantViolation
from finance_god.domain.models import (
    NotificationCategory,
    NotificationPreference,
    WatchlistGroup,
)
from finance_god.infrastructure.persistence.workspace_uow import WorkspaceUnitOfWork


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WatchlistGroupCreate(APIModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)


class WatchlistGroupUpdate(APIModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    expected_revision: int = Field(ge=1)


class WatchlistInstrumentCreate(APIModel):
    instrument_id: str = Field(min_length=1, max_length=160)


class NotificationPreferenceUpdate(APIModel):
    category_preferences: dict[NotificationCategory, bool]


OwnerResolver = Callable[[Request], str]
Model = TypeVar("Model", bound=APIModel)


def create_workspace_routes(
    *,
    session_factory: Callable[[], AsyncSession],
    owner_resolver: OwnerResolver,
) -> list[Route]:
    """Create routes bound to authenticated server-side identity resolution.

    The resolver is deliberately injected by the application shell. These routes do
    not trust a client-provided user header as an authorization boundary.
    """

    async def list_watchlists(request: Request) -> JSONResponse:
        async def action() -> object:
            owner_user_id = _owner(owner_resolver, request)
            async with WorkspaceUnitOfWork(session_factory) as uow:
                return await uow.watchlists.list_groups(owner_user_id)

        return await _respond(action)

    async def create_watchlist_group(request: Request) -> JSONResponse:
        async def action() -> object:
            body = await _body(request, WatchlistGroupCreate)
            owner_user_id = _owner(owner_resolver, request)
            now = datetime.now(UTC)
            group = WatchlistGroup(
                group_id=str(uuid.uuid4()),
                owner_user_id=owner_user_id,
                name=body.name,
                description=body.description,
                revision=1,
                created_at=now,
                updated_at=now,
            )
            async with WorkspaceUnitOfWork(session_factory) as uow:
                created = await uow.watchlists.create_group(group)
                await uow.commit()
                return created

        return await _respond(action, success_status=201)

    async def update_watchlist_group(request: Request) -> JSONResponse:
        async def action() -> object:
            body = await _body(request, WatchlistGroupUpdate)
            owner_user_id = _owner(owner_resolver, request)
            async with WorkspaceUnitOfWork(session_factory) as uow:
                group = await uow.watchlists.get_group(
                    owner_user_id, request.path_params["group_id"]
                )
                if group is None:
                    raise LookupError("watchlist group not found")
                updated = await uow.watchlists.update_group(
                    group.model_copy(
                        update={"name": body.name, "description": body.description}
                    ),
                    expected_revision=body.expected_revision,
                )
                await uow.commit()
                return updated

        return await _respond(action)

    async def add_watchlist_instrument(request: Request) -> JSONResponse:
        async def action() -> object:
            body = await _body(request, WatchlistInstrumentCreate)
            owner_user_id = _owner(owner_resolver, request)
            async with WorkspaceUnitOfWork(session_factory) as uow:
                instrument = await uow.watchlists.add_instrument(
                    owner_user_id=owner_user_id,
                    group_id=request.path_params["group_id"],
                    instrument_id=body.instrument_id,
                    added_by=owner_user_id,
                )
                await uow.commit()
                return instrument

        return await _respond(action, success_status=201)

    async def list_unread_notifications(request: Request) -> JSONResponse:
        async def action() -> object:
            owner_user_id = _owner(owner_resolver, request)
            async with WorkspaceUnitOfWork(session_factory) as uow:
                return await uow.notifications.list_unread(owner_user_id)

        return await _respond(action)

    async def mark_notification_read(request: Request) -> JSONResponse:
        async def action() -> object:
            owner_user_id = _owner(owner_resolver, request)
            async with WorkspaceUnitOfWork(session_factory) as uow:
                await uow.notifications.mark_read(
                    owner_user_id, request.path_params["notification_id"]
                )
                await uow.commit()
                return {"notification_id": request.path_params["notification_id"]}

        return await _respond(action)

    async def get_notification_preferences(request: Request) -> JSONResponse:
        async def action() -> object:
            owner_user_id = _owner(owner_resolver, request)
            async with WorkspaceUnitOfWork(session_factory) as uow:
                preference = await uow.preferences.get(owner_user_id)
                if preference is None:
                    raise LookupError("notification preferences not found")
                return preference

        return await _respond(action)

    async def update_notification_preferences(request: Request) -> JSONResponse:
        async def action() -> object:
            body = await _body(request, NotificationPreferenceUpdate)
            owner_user_id = _owner(owner_resolver, request)
            preference = NotificationPreference(
                owner_user_id=owner_user_id,
                category_preferences=body.category_preferences,
                updated_at=datetime.now(UTC),
            )
            async with WorkspaceUnitOfWork(session_factory) as uow:
                updated = await uow.preferences.update(preference)
                await uow.commit()
                return updated

        return await _respond(action)

    return [
        Route("/watchlists", list_watchlists, methods=["GET"]),
        Route("/watchlists", create_watchlist_group, methods=["POST"]),
        Route("/watchlists/{group_id:str}", update_watchlist_group, methods=["PATCH"]),
        Route(
            "/watchlists/{group_id:str}/instruments",
            add_watchlist_instrument,
            methods=["POST"],
        ),
        Route("/notifications", list_unread_notifications, methods=["GET"]),
        Route(
            "/notifications/{notification_id:str}/read",
            mark_notification_read,
            methods=["POST"],
        ),
        Route("/notification-preferences", get_notification_preferences, methods=["GET"]),
        Route(
            "/notification-preferences",
            update_notification_preferences,
            methods=["PUT"],
        ),
    ]


async def _body(request: Request, model: type[Model]) -> Model:
    return model.model_validate(await request.json())


def _owner(owner_resolver: OwnerResolver, request: Request) -> str:
    owner_user_id = owner_resolver(request).strip()
    if not owner_user_id or len(owner_user_id) > 160:
        raise PermissionError("authenticated owner is required")
    return owner_user_id


async def _respond(
    action: Callable[[], Awaitable[object]], *, success_status: int = 200
) -> JSONResponse:
    try:
        return JSONResponse(_json_value(await action()), status_code=success_status)
    except ValidationError as error:
        return _error("VALIDATION_ERROR", str(error), 422)
    except PermissionError as error:
        return _error("FORBIDDEN", str(error), 403)
    except LookupError as error:
        return _error("NOT_FOUND", str(error), 404)
    except ConcurrentCommandConflict as error:
        return _error("REVISION_CONFLICT", str(error), 409)
    except DomainInvariantViolation as error:
        return _error("DOMAIN_INVARIANT_VIOLATION", str(error), 409)
    except (json.JSONDecodeError, ValueError) as error:
        return _error("INVALID_REQUEST", str(error), 400)


def _json_value(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def _error(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)
