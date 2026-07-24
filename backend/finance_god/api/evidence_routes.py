"""Read-only HTTP surface for structured process evidence (T10).

These routes expose immutable evidence bundles by ``(object_type,
object_id, version)`` for the process/evidence drawer and the advanced
evidence page. They never fabricate content: a missing bundle yields an
explicit 404 so the frontend renders a visible empty/failure state.

Access tiers:
- ``normal``   (default) read-only conclusion content;
- ``advanced`` adds agent workflow nodes and routing notices.
The ``internal`` tier (raw error traces) is reserved for in-process
operator tooling and is never served over HTTP.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from finance_god.api.auth import AuthenticationError, OwnerResolver
from finance_god.application.evidence_service import EvidenceService, EvidenceTier
from finance_god.domain import ConcurrentCommandConflict

ServiceProvider = Callable[[], EvidenceService]

_PUBLIC_TIERS = {"normal": EvidenceTier.NORMAL, "advanced": EvidenceTier.ADVANCED}


class _APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceExportRequest(_APIModel):
    version: str | None = Field(default=None, max_length=80)
    tier: str = Field(default="normal")


def create_evidence_routes(
    *,
    service_provider: ServiceProvider,
    owner_resolver: OwnerResolver,
) -> list[Route]:
    async def get_evidence(request: Request) -> JSONResponse:
        async def action() -> object:
            owner_id = await _owner(owner_resolver, request)
            tier = _tier(request.query_params.get("tier"))
            return await service_provider().get(
                owner_id=owner_id,
                object_type=request.path_params["object_type"],
                object_id=request.path_params["object_id"],
                version=_version(request),
                tier=tier,
            )

        return await _respond(action)

    async def get_lineage(request: Request) -> JSONResponse:
        async def action() -> object:
            owner_id = await _owner(owner_resolver, request)
            return await service_provider().lineage(
                owner_id=owner_id,
                object_type=request.path_params["object_type"],
                object_id=request.path_params["object_id"],
                version=_version(request),
            )

        return await _respond(action)

    async def compare_versions(request: Request) -> JSONResponse:
        async def action() -> object:
            owner_id = await _owner(owner_resolver, request)
            version_a = _required_query(request, "a")
            version_b = _required_query(request, "b")
            return await service_provider().compare(
                owner_id=owner_id,
                object_type=request.path_params["object_type"],
                object_id=request.path_params["object_id"],
                version_a=version_a,
                version_b=version_b,
            )

        return await _respond(action)

    async def export_bundle(request: Request) -> JSONResponse:
        async def action() -> object:
            owner_id = await _owner(owner_resolver, request)
            body = EvidenceExportRequest.model_validate(await request.json())
            return await service_provider().export(
                owner_id=owner_id,
                object_type=request.path_params["object_type"],
                object_id=request.path_params["object_id"],
                version=body.version,
                tier=_tier(body.tier),
            )

        return await _respond(action)

    return [
        Route(
            "/{object_type:str}/{object_id:str}/lineage",
            get_lineage,
            methods=["GET"],
        ),
        Route(
            "/{object_type:str}/{object_id:str}/versions/compare",
            compare_versions,
            methods=["GET"],
        ),
        Route(
            "/{object_type:str}/{object_id:str}/export",
            export_bundle,
            methods=["POST"],
        ),
        Route(
            "/{object_type:str}/{object_id:str}",
            get_evidence,
            methods=["GET"],
        ),
    ]


class _TierForbidden(Exception):
    """Raised when a caller requests a tier not served over HTTP."""


def _tier(raw: str | None) -> EvidenceTier:
    value = (raw or "normal").strip().lower()
    if value == "internal":
        raise _TierForbidden("the internal evidence tier is not available over HTTP")
    tier = _PUBLIC_TIERS.get(value)
    if tier is None:
        raise ValueError("tier must be one of: normal, advanced")
    return tier


def _version(request: Request) -> str | None:
    value = request.query_params.get("version")
    return value.strip() if value and value.strip() else None


def _required_query(request: Request, name: str) -> str:
    value = (request.query_params.get(name) or "").strip()
    if not value or len(value) > 80:
        raise ValueError(f"query parameter '{name}' is required")
    return value


async def _owner(owner_resolver: OwnerResolver, request: Request) -> str:
    owner_user_id = (await owner_resolver(request)).strip()
    if not owner_user_id or len(owner_user_id) > 160:
        raise AuthenticationError("authenticated owner is required")
    return owner_user_id


async def _respond(action: Callable[[], Awaitable[object]]) -> JSONResponse:
    try:
        value = await action()
        if isinstance(value, BaseModel):
            value = value.model_dump(mode="json")
        return JSONResponse(value, status_code=200)
    except ValidationError as error:
        return _error("VALIDATION_ERROR", str(error), 422)
    except AuthenticationError as error:
        return _error("UNAUTHORIZED", str(error), 401)
    except _TierForbidden as error:
        return _error("FORBIDDEN_TIER", str(error), 403)
    except PermissionError as error:
        return _error("NOT_FOUND", str(error), 404)
    except LookupError as error:
        return _error("NOT_FOUND", str(error), 404)
    except ConcurrentCommandConflict as error:
        return _error("REVISION_CONFLICT", str(error), 409)
    except ValueError as error:
        return _error("INVALID_REQUEST", str(error), 400)


def _error(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message}}, status_code=status
    )
