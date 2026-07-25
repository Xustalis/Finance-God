from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from finance_god.api.auth import AuthenticationError, OwnerResolver
from finance_god.application.candidate_service import (
    CandidateScoringService,
    candidates_for_profile,
)
from finance_god.application.idempotency import canonical_request_hash
from finance_god.domain.errors import (
    ConcurrentCommandConflict,
    DomainInvariantViolation,
    IdempotencyConflict,
)
from finance_god.domain.models import (
    NotificationCategory,
    NotificationPreference,
    WatchlistGroup,
)
from finance_god.infrastructure.persistence.workspace_uow import WorkspaceUnitOfWork

CandidateIgnoreReason = Literal[
    "not_now", "already_covered", "disagree", "data_error"
]


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WatchlistGroupCreate(APIModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)


class WatchlistGroupUpdate(APIModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    expected_revision: int = Field(ge=1)


class WatchlistGroupDelete(APIModel):
    expected_revision: int = Field(ge=1)


class WatchlistInstrumentCreate(APIModel):
    instrument_id: str = Field(min_length=1, max_length=160)


class CandidateIgnoreCreate(APIModel):
    reason: CandidateIgnoreReason
    note: str | None = Field(default=None, max_length=500)


class NotificationPreferenceUpdate(APIModel):
    category_preferences: dict[NotificationCategory, bool]


CandidateServiceProvider = Callable[[], CandidateScoringService]
CandidateProfileProvider = Callable[[str], Awaitable[dict | None]]
Model = TypeVar("Model", bound=APIModel)
IDEMPOTENCY_HEADER = "idempotency-key"


def create_workspace_routes(
    *,
    session_factory: Callable[[], AsyncSession],
    owner_resolver: OwnerResolver,
    candidate_service_provider: CandidateServiceProvider | None = None,
    candidate_profile_provider: CandidateProfileProvider | None = None,
) -> list[Route]:
    """Create routes bound to authenticated server-side identity resolution.

    The resolver is deliberately injected by the application shell. These routes do
    not trust a client-provided user header as an authorization boundary.
    """

    async def list_watchlists(request: Request) -> JSONResponse:
        async def action() -> object:
            owner_user_id = await _owner(owner_resolver, request)
            async with WorkspaceUnitOfWork(session_factory) as uow:
                return await uow.watchlists.list_groups(owner_user_id)

        return await _respond(action)

    async def create_watchlist_group(request: Request) -> JSONResponse:
        async def action() -> object:
            body = await _body(request, WatchlistGroupCreate)
            owner_user_id = await _owner(owner_resolver, request)

            async def mutate(uow: WorkspaceUnitOfWork) -> object:
                now = datetime.now(UTC)
                return await uow.watchlists.create_group(
                    WatchlistGroup(
                        group_id=str(uuid.uuid4()),
                        owner_user_id=owner_user_id,
                        name=body.name,
                        description=body.description,
                        revision=1,
                        created_at=now,
                        updated_at=now,
                    )
                )

            return await _idempotent_workspace_command(
                session_factory=session_factory,
                request=request,
                owner_user_id=owner_user_id,
                scope="workspace.watchlist.create",
                payload=body.model_dump(mode="json"),
                mutate=mutate,
            )

        return await _respond(action, success_status=201)

    async def update_watchlist_group(request: Request) -> JSONResponse:
        async def action() -> object:
            body = await _body(request, WatchlistGroupUpdate)
            owner_user_id = await _owner(owner_resolver, request)

            async def mutate(uow: WorkspaceUnitOfWork) -> object:
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
                return updated

            return await _idempotent_workspace_command(
                session_factory=session_factory,
                request=request,
                owner_user_id=owner_user_id,
                scope="workspace.watchlist.update",
                payload=body.model_dump(mode="json"),
                mutate=mutate,
            )

        return await _respond(action)

    async def add_watchlist_instrument(request: Request) -> JSONResponse:
        async def action() -> object:
            body = await _body(request, WatchlistInstrumentCreate)
            owner_user_id = await _owner(owner_resolver, request)

            async def mutate(uow: WorkspaceUnitOfWork) -> object:
                return await uow.watchlists.add_instrument(
                    owner_user_id=owner_user_id,
                    group_id=request.path_params["group_id"],
                    instrument_id=body.instrument_id,
                    added_by=owner_user_id,
                )

            return await _idempotent_workspace_command(
                session_factory=session_factory,
                request=request,
                owner_user_id=owner_user_id,
                scope="workspace.watchlist.instrument.add",
                payload=body.model_dump(mode="json"),
                mutate=mutate,
            )

        return await _respond(action, success_status=201)

    async def list_watchlist_instruments(request: Request) -> JSONResponse:
        async def action() -> object:
            owner_user_id = await _owner(owner_resolver, request)
            async with WorkspaceUnitOfWork(session_factory) as uow:
                return await uow.watchlists.list_instruments(
                    owner_user_id, request.path_params["group_id"]
                )

        return await _respond(action)

    async def delete_watchlist_group(request: Request) -> JSONResponse:
        async def action() -> object:
            body = await _body(request, WatchlistGroupDelete)
            owner_user_id = await _owner(owner_resolver, request)

            async def mutate(uow: WorkspaceUnitOfWork) -> object:
                group = await uow.watchlists.get_group(
                    owner_user_id, request.path_params["group_id"]
                )
                if group is None:
                    raise LookupError("watchlist group not found")
                await uow.watchlists.delete_group(
                    owner_user_id,
                    request.path_params["group_id"],
                    expected_revision=body.expected_revision,
                )
                return {"group_id": request.path_params["group_id"], "deleted": True}

            return await _idempotent_workspace_command(
                session_factory=session_factory,
                request=request,
                owner_user_id=owner_user_id,
                scope="workspace.watchlist.delete",
                payload=body.model_dump(mode="json"),
                mutate=mutate,
            )

        return await _respond(action)

    async def remove_watchlist_instrument(request: Request) -> JSONResponse:
        async def action() -> object:
            owner_user_id = await _owner(owner_resolver, request)

            async def mutate(uow: WorkspaceUnitOfWork) -> object:
                await uow.watchlists.remove_instrument(
                    owner_user_id,
                    request.path_params["group_id"],
                    request.path_params["instrument_id"],
                )
                return {
                    "group_id": request.path_params["group_id"],
                    "instrument_id": request.path_params["instrument_id"],
                    "removed": True,
                }

            return await _idempotent_workspace_command(
                session_factory=session_factory,
                request=request,
                owner_user_id=owner_user_id,
                scope="workspace.watchlist.instrument.remove",
                payload={},
                mutate=mutate,
            )

        return await _respond(action)

    async def list_candidates(request: Request) -> JSONResponse:
        async def action() -> object:
            if candidate_service_provider is None:
                raise _Unavailable("candidate scoring is not configured")
            owner_user_id = await _owner(owner_resolver, request)
            async with WorkspaceUnitOfWork(session_factory) as uow:
                ignores = await uow.candidate_ignores.list(owner_user_id)
            ignored = {row.instrument_id: row.reason for row in ignores}
            service = candidate_service_provider()
            if candidate_profile_provider is not None:
                return await candidates_for_profile(
                    service=service,
                    owner_id=owner_user_id,
                    now=datetime.now(UTC),
                    profile=await candidate_profile_provider(owner_user_id),
                    ignored=ignored,
                )
            return await service.candidates(
                owner_id=owner_user_id,
                now=datetime.now(UTC),
                ignored=ignored,
            )

        return await _respond(action)

    async def ignore_candidate(request: Request) -> JSONResponse:
        async def action() -> object:
            body = await _body(request, CandidateIgnoreCreate)
            owner_user_id = await _owner(owner_resolver, request)

            async def mutate(uow: WorkspaceUnitOfWork) -> object:
                return await uow.candidate_ignores.upsert(
                    owner_user_id=owner_user_id,
                    instrument_id=request.path_params["instrument_id"],
                    reason=body.reason,
                    note=body.note,
                )

            return await _idempotent_workspace_command(
                session_factory=session_factory,
                request=request,
                owner_user_id=owner_user_id,
                scope="workspace.candidate.ignore",
                payload=body.model_dump(mode="json"),
                mutate=mutate,
            )

        return await _respond(action, success_status=201)

    async def unignore_candidate(request: Request) -> JSONResponse:
        async def action() -> object:
            owner_user_id = await _owner(owner_resolver, request)

            async def mutate(uow: WorkspaceUnitOfWork) -> object:
                await uow.candidate_ignores.remove(
                    owner_user_id, request.path_params["instrument_id"]
                )
                return {
                    "instrument_id": request.path_params["instrument_id"],
                    "ignored": False,
                }

            return await _idempotent_workspace_command(
                session_factory=session_factory,
                request=request,
                owner_user_id=owner_user_id,
                scope="workspace.candidate.unignore",
                payload={},
                mutate=mutate,
            )

        return await _respond(action)

    async def list_unread_notifications(request: Request) -> JSONResponse:
        async def action() -> object:
            owner_user_id = await _owner(owner_resolver, request)
            async with WorkspaceUnitOfWork(session_factory) as uow:
                return await uow.notifications.list_unread(owner_user_id)

        return await _respond(action)

    async def list_notification_history(request: Request) -> JSONResponse:
        """Return recent notifications including read ones.

        Query params:
        - limit: 1..200 (default 50)
        - include_read: true|false (default true)
        - cursor: last notification_id from the previous page

        Toast hide ≠ read ≠ handled. History only exposes persisted unread|read.
        """

        async def action() -> object:
            owner_user_id = await _owner(owner_resolver, request)
            raw_limit = request.query_params.get("limit", "50")
            try:
                limit = int(raw_limit)
            except (TypeError, ValueError) as error:
                raise ValueError("limit must be an integer") from error
            include_read_raw = request.query_params.get("include_read", "true").strip().lower()
            if include_read_raw not in {"true", "false", "1", "0"}:
                raise ValueError("include_read must be true or false")
            include_read = include_read_raw in {"true", "1"}
            async with WorkspaceUnitOfWork(session_factory) as uow:
                return await uow.notifications.list_history(
                    owner_user_id,
                    limit=limit,
                    include_read=include_read,
                    cursor=request.query_params.get("cursor"),
                )

        return await _respond(action)

    async def mark_notification_read(request: Request) -> JSONResponse:
        async def action() -> object:
            owner_user_id = await _owner(owner_resolver, request)
            async with WorkspaceUnitOfWork(session_factory) as uow:
                await uow.notifications.mark_read(
                    owner_user_id, request.path_params["notification_id"]
                )
                await uow.commit()
                return {"notification_id": request.path_params["notification_id"]}

        return await _respond(action)

    async def get_notification_preferences(request: Request) -> JSONResponse:
        async def action() -> object:
            owner_user_id = await _owner(owner_resolver, request)
            async with WorkspaceUnitOfWork(session_factory) as uow:
                preference = await uow.preferences.get(owner_user_id)
                if preference is None:
                    raise LookupError("notification preferences not found")
                return preference

        return await _respond(action)

    async def update_notification_preferences(request: Request) -> JSONResponse:
        async def action() -> object:
            body = await _body(request, NotificationPreferenceUpdate)
            owner_user_id = await _owner(owner_resolver, request)
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
        Route(
            "/watchlists/{group_id:str}/instruments",
            list_watchlist_instruments,
            methods=["GET"],
        ),
        Route(
            "/watchlists/{group_id:str}",
            delete_watchlist_group,
            methods=["DELETE"],
        ),
        Route(
            "/watchlists/{group_id:str}/instruments/{instrument_id:str}",
            remove_watchlist_instrument,
            methods=["DELETE"],
        ),
        Route("/candidates", list_candidates, methods=["GET"]),
        Route(
            "/candidates/{instrument_id:str}/ignore",
            ignore_candidate,
            methods=["POST"],
        ),
        Route(
            "/candidates/{instrument_id:str}/ignore",
            unignore_candidate,
            methods=["DELETE"],
        ),
        Route("/notifications", list_unread_notifications, methods=["GET"]),
        Route(
            "/notifications/history",
            list_notification_history,
            methods=["GET"],
        ),
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


class _Unavailable(RuntimeError):
    """A required dependency is not configured; surfaces as an explicit 503."""


async def _owner(owner_resolver: OwnerResolver, request: Request) -> str:
    owner_user_id = (await owner_resolver(request)).strip()
    if not owner_user_id or len(owner_user_id) > 160:
        raise AuthenticationError("authenticated owner is required")
    return owner_user_id


async def _idempotent_workspace_command(
    *,
    session_factory: Callable[[], AsyncSession],
    request: Request,
    owner_user_id: str,
    scope: str,
    payload: object,
    mutate: Callable[[WorkspaceUnitOfWork], Awaitable[object]],
) -> object:
    key = _idempotency_key(request)
    request_hash = _request_hash(request, payload)
    async with WorkspaceUnitOfWork(session_factory) as uow:
        await uow.locks.owner(owner_user_id)
        prior = await uow.idempotency.get(scope, owner_user_id, key)
        if prior is not None:
            if prior.request_hash != request_hash:
                raise IdempotencyConflict(
                    "idempotency key was already used with a different request"
                )
            if prior.response_json is None:
                raise RuntimeError("workspace idempotency response is missing")
            return prior.response_json

        result = await mutate(uow)
        response_json = _json_value(result)
        await uow.idempotency.add(
            scope=scope,
            owner_user_id=owner_user_id,
            key=key,
            request_hash=request_hash,
            result_reference=key,
            response_json=response_json,
            created_at=datetime.now(UTC),
        )
        await uow.flush()
        await uow.commit()
        return result


def _idempotency_key(request: Request) -> str:
    key = request.headers.get(IDEMPOTENCY_HEADER, "").strip()
    if not key:
        raise ValueError(f"{IDEMPOTENCY_HEADER} is required")
    if len(key) > 160:
        raise ValueError(f"{IDEMPOTENCY_HEADER} must not exceed 160 characters")
    return key


def _request_hash(request: Request, payload: object) -> str:
    return canonical_request_hash(
        {
            "method": request.method,
            "path": request.url.path,
            "payload": payload,
        }
    )


async def _respond(
    action: Callable[[], Awaitable[object]], *, success_status: int = 200
) -> JSONResponse:
    try:
        return JSONResponse(_json_value(await action()), status_code=success_status)
    except ValidationError as error:
        return _error("VALIDATION_ERROR", str(error), 422)
    except AuthenticationError as error:
        return _error("UNAUTHORIZED", str(error), 401)
    except PermissionError as error:
        return _error("NOT_FOUND", str(error), 404)
    except LookupError as error:
        return _error("NOT_FOUND", str(error), 404)
    except IdempotencyConflict as error:
        return _error("IDEMPOTENCY_CONFLICT", str(error), 409)
    except ConcurrentCommandConflict as error:
        return _error("REVISION_CONFLICT", str(error), 409)
    except DomainInvariantViolation as error:
        return _error("DOMAIN_INVARIANT_VIOLATION", str(error), 409)
    except _Unavailable as error:
        return _error("DEPENDENCY_UNAVAILABLE", str(error), 503)
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
