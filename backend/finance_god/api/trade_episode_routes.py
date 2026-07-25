from __future__ import annotations

from collections.abc import Awaitable, Callable

from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from finance_god.api.auth import AuthenticationError, OwnerResolver
from finance_god.trade_review import TradeReviewService


def create_trade_episode_routes(
    *, service: TradeReviewService, owner_resolver: OwnerResolver
) -> list[Route]:
    async def listing(request: Request) -> JSONResponse:
        async def action() -> object:
            return await service.list_episodes(
                owner_id=await await_owner(request),
                instrument_id=request.query_params.get("instrument_id") or None,
                status=request.query_params.get("status") or None,
                review_status=request.query_params.get("review_status") or None,
            )
        return await _respond(action)

    async def detail(request: Request) -> JSONResponse:
        async def action() -> object:
            return await service.get_episode(
                owner_id=await await_owner(request),
                episode_id=request.path_params["episode_id"],
            )
        return await _respond(action)

    async def decisions(request: Request) -> JSONResponse:
        async def action() -> object:
            return await service.decisions(
                owner_id=await await_owner(request),
                episode_id=request.path_params["episode_id"],
            )
        return await _respond(action)

    async def review(request: Request) -> JSONResponse:
        async def action() -> object:
            return await service.get_review(
                owner_id=await await_owner(request),
                episode_id=request.path_params["episode_id"],
            )
        return await _respond(action)

    async def retry(request: Request) -> JSONResponse:
        key = request.headers.get("idempotency-key", "").strip()
        if not key or len(key) > 200:
            return _error("INVALID_REQUEST", "a valid idempotency-key header is required", 400)
        async def action() -> object:
            return await service.retry_review(
                owner_id=await await_owner(request),
                episode_id=request.path_params["episode_id"],
            )
        return await _respond(action)

    async def await_owner_value(request: Request) -> str:
        owner = (await owner_resolver(request)).strip()
        if not owner:
            raise AuthenticationError("authenticated owner is required")
        return owner

    await_owner = await_owner_value
    return [
        Route("/", listing, methods=["GET"]),
        Route("/{episode_id:str}", detail, methods=["GET"]),
        Route("/{episode_id:str}/decisions", decisions, methods=["GET"]),
        Route("/{episode_id:str}/review", review, methods=["GET"]),
        Route("/{episode_id:str}/review/retry", retry, methods=["POST"]),
    ]


async def _respond(action: Callable[[], Awaitable[object]]) -> JSONResponse:
    try:
        value = await action()
        if isinstance(value, BaseModel):
            value = value.model_dump(mode="json")
        elif isinstance(value, tuple):
            value = [item.model_dump(mode="json") for item in value]
        return JSONResponse({"success": True, "data": value, "error": None, "meta": {}})
    except AuthenticationError as error:
        return _error("UNAUTHORIZED", str(error), 401)
    except LookupError as error:
        return _error("NOT_FOUND", str(error), 404)
    except ValueError as error:
        return _error("INVALID_REQUEST", str(error), 400)


def _error(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse(
        {"success": False, "data": None, "error": {"code": code, "message": message}, "meta": {}},
        status_code=status,
    )
