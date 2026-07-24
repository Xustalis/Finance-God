from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Protocol, TypeVar

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from finance_god.api.auth import AuthenticationError, OwnerResolver
from finance_god.application.mandate_service import (
    MandateService,
    MandateSpec,
    OrderIntentProbe,
)
from finance_god.domain.errors import (
    ConcurrentCommandConflict,
    DomainInvariantViolation,
)
from finance_god.execution.contracts import StoredDraft, StoredOrder
from finance_god.trading.access import (
    AuthorizationLimits,
    AuthorizationStatus,
    AutonomyLevel,
)
from finance_god.trading.mandate import order_notional


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MandateSave(APIModel):
    expected_revision: int = Field(ge=1)
    autonomy_level: AutonomyLevel
    allowed_markets: tuple[str, ...] = Field(min_length=1)
    allowed_assets: tuple[str, ...] = Field(min_length=1)
    allowed_sides: tuple[str, ...] = Field(min_length=1)
    allowed_order_types: tuple[str, ...] = Field(min_length=1)
    short_markets: tuple[str, ...] = ()
    limits: AuthorizationLimits
    valid_until: AwareDatetime
    note: str | None = Field(default=None, max_length=500)


class MandateStatusChange(APIModel):
    expected_revision: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=500)


class _OrdersService(Protocol):
    async def list_orders(self, *, owner_id: str) -> tuple[StoredOrder, ...]: ...

    async def get_draft(self, *, owner_id: str, draft_id: str) -> StoredDraft: ...


OrdersProvider = Callable[[], _OrdersService | None]
Model = TypeVar("Model", bound=APIModel)


def create_mandate_routes(
    *,
    session_factory: Callable[[], AsyncSession],
    owner_resolver: OwnerResolver,
    clock,
    ids,
    orders_provider: OrdersProvider | None = None,
) -> list[Route]:
    """Create the /mandate routes bound to server-side identity resolution."""
    service = MandateService(session_factory=session_factory, clock=clock, ids=ids)

    async def get_current(request: Request) -> JSONResponse:
        async def action() -> object:
            owner_id = await _owner(owner_resolver, request)
            return await service.ensure_current(owner_id)

        return await _respond(action)

    async def get_history(request: Request) -> JSONResponse:
        async def action() -> object:
            owner_id = await _owner(owner_resolver, request)
            return await service.history(owner_id)

        return await _respond(action)

    async def save(request: Request) -> JSONResponse:
        async def action() -> object:
            body = await _body(request, MandateSave)
            owner_id = await _owner(owner_resolver, request)
            spec = MandateSpec(
                autonomy_level=body.autonomy_level,
                allowed_markets=body.allowed_markets,
                allowed_assets=body.allowed_assets,
                allowed_sides=body.allowed_sides,
                allowed_order_types=body.allowed_order_types,
                short_markets=body.short_markets,
                limits=body.limits,
                valid_until=body.valid_until,
                note=body.note,
            )
            return await service.save_version(
                owner_id, expected_revision=body.expected_revision, spec=spec
            )

        return await _respond(action, success_status=201)

    def _status_route(status: AuthorizationStatus):
        async def handler(request: Request) -> JSONResponse:
            async def action() -> object:
                body = await _body(request, MandateStatusChange)
                owner_id = await _owner(owner_resolver, request)
                return await service.set_status(
                    owner_id,
                    expected_revision=body.expected_revision,
                    status=status,
                    note=body.note,
                )

            return await _respond(action)

        return handler

    async def get_impact(request: Request) -> JSONResponse:
        async def action() -> object:
            owner_id = await _owner(owner_resolver, request)
            probes = await _order_probes(orders_provider, owner_id)
            return await service.impact(owner_id, probes)

        return await _respond(action)

    return [
        Route("/current", get_current, methods=["GET"]),
        Route("/history", get_history, methods=["GET"]),
        Route("/impact", get_impact, methods=["GET"]),
        Route("/versions", save, methods=["POST"]),
        Route("/pause", _status_route(AuthorizationStatus.PAUSED), methods=["POST"]),
        Route("/resume", _status_route(AuthorizationStatus.ACTIVE), methods=["POST"]),
        Route("/revoke", _status_route(AuthorizationStatus.REVOKED), methods=["POST"]),
    ]


async def _order_probes(
    orders_provider: OrdersProvider | None, owner_id: str
) -> tuple[OrderIntentProbe, ...]:
    if orders_provider is None:
        return ()
    orders = orders_provider()
    if orders is None:
        return ()
    stored_orders = await orders.list_orders(owner_id=owner_id)
    probes: list[OrderIntentProbe] = []
    seen: set[str] = set()
    for stored in stored_orders:
        draft_id = stored.draft_reference.object_id
        if draft_id in seen:
            continue
        seen.add(draft_id)
        stored_draft = await orders.get_draft(owner_id=owner_id, draft_id=draft_id)
        order = stored_draft.draft
        probes.append(
            OrderIntentProbe(
                reference=order.draft_id,
                instrument_id=order.instrument_id,
                side=order.side.value,
                order_type=order.order_type.value,
                notional=order_notional(
                    order_type=order.order_type.value,
                    quantity=order.quantity,
                    amount=order.amount,
                    limit_price=order.limit_price,
                    reference_price=stored_draft.reference_price,
                ),
            )
        )
    return tuple(probes)


async def _body(request: Request, model: type[Model]) -> Model:
    return model.model_validate(await request.json())


async def _owner(owner_resolver: OwnerResolver, request: Request) -> str:
    owner_user_id = (await owner_resolver(request)).strip()
    if not owner_user_id or len(owner_user_id) > 160:
        raise AuthenticationError("authenticated owner is required")
    return owner_user_id


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
