from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from finance_god.api.auth import AuthenticationError, OwnerResolver
from finance_god.application.trade_plan_service import (
    TradePlanActionRevision,
    TradePlanService,
)
from finance_god.domain import ConcurrentCommandConflict, DomainInvariantViolation
from finance_god.execution import ExecutionFailure

IDEMPOTENCY_HEADER = "idempotency-key"


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CandidatePlanCreate(APIModel):
    instrument_id: str = Field(min_length=1, max_length=160)


class TradePlanRevisionRequest(APIModel):
    expected_revision: int = Field(ge=1)
    actions: tuple[TradePlanActionRevision, ...] = Field(min_length=1)


class TradePlanConfirmRequest(APIModel):
    expected_revision: int = Field(ge=1)


Model = TypeVar("Model", bound=APIModel)
ServiceProvider = Callable[[], TradePlanService]


def create_trade_plan_routes(
    *,
    service_provider: ServiceProvider,
    owner_resolver: OwnerResolver,
) -> list[Route]:
    async def create_candidate_plan(request: Request) -> JSONResponse:
        async def action() -> object:
            body = await _body(request, CandidatePlanCreate)
            return await service_provider().create_from_candidate(
                owner_id=await _owner(owner_resolver, request),
                instrument_id=body.instrument_id,
                idempotency_key=_idempotency_key(request),
            )

        return await _respond(action, success_status=201)

    async def create_deviation_plan(request: Request) -> JSONResponse:
        async def action() -> object:
            return await service_provider().create_from_portfolio_deviation(
                owner_id=await _owner(owner_resolver, request),
                idempotency_key=_idempotency_key(request),
            )

        return await _respond(action, success_status=201)

    async def get_plan(request: Request) -> JSONResponse:
        async def action() -> object:
            return await service_provider().get(
                owner_id=await _owner(owner_resolver, request),
                plan_id=request.path_params["plan_id"],
            )

        return await _respond(action)

    async def revise_plan(request: Request) -> JSONResponse:
        async def action() -> object:
            body = await _body(request, TradePlanRevisionRequest)
            return await service_provider().revise(
                owner_id=await _owner(owner_resolver, request),
                plan_id=request.path_params["plan_id"],
                expected_revision=body.expected_revision,
                actions=body.actions,
            )

        return await _respond(action)

    async def confirm_plan(request: Request) -> JSONResponse:
        async def action() -> object:
            body = await _body(request, TradePlanConfirmRequest)
            return await service_provider().confirm_and_generate(
                owner_id=await _owner(owner_resolver, request),
                plan_id=request.path_params["plan_id"],
                expected_revision=body.expected_revision,
                idempotency_key=_idempotency_key(request),
            )

        return await _respond(action)

    return [
        Route("/from-candidate", create_candidate_plan, methods=["POST"]),
        Route(
            "/from-portfolio-deviation",
            create_deviation_plan,
            methods=["POST"],
        ),
        Route("/{plan_id:str}", get_plan, methods=["GET"]),
        Route("/{plan_id:str}/versions", revise_plan, methods=["POST"]),
        Route(
            "/{plan_id:str}/confirm-and-generate",
            confirm_plan,
            methods=["POST"],
        ),
    ]


async def _body(request: Request, model: type[Model]) -> Model:
    return model.model_validate(await request.json())


async def _owner(owner_resolver: OwnerResolver, request: Request) -> str:
    owner_user_id = (await owner_resolver(request)).strip()
    if not owner_user_id or len(owner_user_id) > 160:
        raise AuthenticationError("authenticated owner is required")
    return owner_user_id


def _idempotency_key(request: Request) -> str:
    key = request.headers.get(IDEMPOTENCY_HEADER, "").strip()
    if not key or len(key) > 200:
        raise ValueError("a valid idempotency-key header is required")
    return key


async def _respond(
    action: Callable[[], Awaitable[object]], *, success_status: int = 200
) -> JSONResponse:
    try:
        value = await action()
        if isinstance(value, BaseModel):
            value = value.model_dump(mode="json")
        return JSONResponse(value, status_code=success_status)
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
        return _error("PLAN_BLOCKED", str(error), 409)
    except ExecutionFailure as error:
        return _error(error.code.value, str(error), 409)
    except (json.JSONDecodeError, ValueError) as error:
        return _error("INVALID_REQUEST", str(error), 400)


def _error(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)
