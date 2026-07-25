from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Protocol, TypeVar

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from finance_god.api.auth import AuthenticationError, OwnerResolver
from finance_god.application.decision_inbox import DecisionInboxService
from finance_god.application.portfolio_query import PortfolioQueryService
from finance_god.domain import (
    ConcurrentCommandConflict,
    DomainInvariantViolation,
    OrderSide,
    OrderType,
    TimeInForce,
    VersionReference,
)
from finance_god.execution import (
    DraftMode,
    ExecutionFailure,
    SimulationExecutionService,
)

IDEMPOTENCY_HEADER = "idempotency-key"
MarketReferenceProvider = Callable[
    [str],
    Awaitable[tuple[Decimal, VersionReference]],
]


class SimulationServiceUnavailable(RuntimeError):
    """A required server-side simulation dependency is not available."""


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SimulationAccountCreate(APIModel):
    initial_cash_rmb: Decimal = Field(gt=0)


class SimulationAccountReset(APIModel):
    initial_cash_rmb: Decimal = Field(gt=0)


class SimulationAccountView(APIModel):
    account_id: str
    owner_id: str
    status: str
    cash_total_rmb: Decimal
    cash_available_rmb: Decimal
    cash_frozen_rmb: Decimal
    margin_rmb: Decimal
    revision: int = Field(ge=1)


class SimulationPositionView(APIModel):
    account_id: str
    instrument_id: str
    currency: str
    long_quantity: Decimal
    settled_quantity: Decimal
    frozen_quantity: Decimal
    cost_rmb: Decimal
    revision: int = Field(ge=0)


class DraftCreateRequest(APIModel):
    mode: DraftMode
    account_id: str = Field(min_length=1, max_length=160)
    instrument_id: str = Field(min_length=1, max_length=160)
    side: OrderSide
    order_type: OrderType
    quantity: Decimal | None = Field(default=None, gt=0)
    amount: Decimal | None = Field(default=None, gt=0)
    limit_price: Decimal | None = Field(default=None, gt=0)
    reference_price: Decimal | None = Field(default=None, gt=0)
    time_in_force: TimeInForce | None = None
    fund_rule_version: VersionReference | None = None
    valid_until: AwareDatetime
    input_versions: tuple[VersionReference, ...] = Field(min_length=1)
    plan_reference: VersionReference | None = None


class ExpectedRevisionRequest(APIModel):
    expected_revision: int = Field(ge=1)


class SoftRiskConfirmationRequest(APIModel):
    seen_reason_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class DraftConfirmationRequest(ExpectedRevisionRequest):
    seen_summary_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class SimulationAccountApplication(Protocol):
    async def create(
        self,
        *,
        owner_id: str,
        request: SimulationAccountCreate,
        idempotency_key: str,
        request_hash: str,
    ) -> SimulationAccountView: ...

    async def reset(
        self,
        *,
        owner_id: str,
        account_id: str,
        request: SimulationAccountReset,
        idempotency_key: str,
        request_hash: str,
    ) -> SimulationAccountView: ...

    async def current(self, *, owner_id: str) -> SimulationAccountView | None: ...

    async def positions(
        self, *, owner_id: str
    ) -> tuple[SimulationPositionView, ...]: ...


def create_simulation_routes(
    *,
    execution: SimulationExecutionService,
    accounts: SimulationAccountApplication,
    portfolio: PortfolioQueryService,
    decision_inbox: DecisionInboxService,
    owner_resolver: OwnerResolver,
    market_reference_provider: MarketReferenceProvider | None = None,
) -> list[Route]:
    async def create_account(request: Request) -> JSONResponse:
        async def action() -> object:
            body = await _body(request, SimulationAccountCreate)
            return await accounts.create(
                owner_id=await _owner(owner_resolver, request),
                request=body,
                idempotency_key=_idempotency_key(request),
                request_hash=_request_hash(body),
            )

        return await _respond(action, success_status=201)

    async def reset_account(request: Request) -> JSONResponse:
        async def action() -> object:
            body = await _body(request, SimulationAccountReset)
            return await accounts.reset(
                owner_id=await _owner(owner_resolver, request),
                account_id=request.path_params["account_id"],
                request=body,
                idempotency_key=_idempotency_key(request),
                request_hash=_request_hash(body),
            )

        return await _respond(action)

    async def current_account(request: Request) -> JSONResponse:
        async def action() -> object:
            account = await accounts.current(owner_id=await _owner(owner_resolver, request))
            if account is None:
                raise LookupError("simulation account not found")
            return account

        return await _respond(action)

    async def current_positions(request: Request) -> JSONResponse:
        async def action() -> object:
            owner_id = await _owner(owner_resolver, request)
            return await accounts.positions(owner_id=owner_id)

        return await _respond(action)

    async def create_draft(request: Request) -> JSONResponse:
        async def action() -> object:
            body = await _body(request, DraftCreateRequest)
            if market_reference_provider is None:
                raise SimulationServiceUnavailable(
                    "trusted market reference provider is unavailable"
                )
            trusted_price, trusted_version = await market_reference_provider(
                body.instrument_id
            )
            if (
                body.reference_price is not None
                and body.reference_price != trusted_price
            ):
                raise ValueError(
                    "market reference changed; refresh the quote before creating a draft"
                )
            submitted_market_version = next(
                (
                    item
                    for item in body.input_versions
                    if item.object_type == trusted_version.object_type
                    and item.object_id == trusted_version.object_id
                ),
                None,
            )
            if (
                submitted_market_version is not None
                and submitted_market_version != trusted_version
            ):
                raise ValueError(
                    "market reference version changed; refresh before creating a draft"
                )
            return await execution.create_order_draft(
                owner_id=await _owner(owner_resolver, request),
                mode=body.mode,
                account_id=body.account_id,
                instrument_id=body.instrument_id,
                side=body.side,
                order_type=body.order_type,
                quantity=body.quantity,
                amount=body.amount,
                limit_price=body.limit_price,
                time_in_force=body.time_in_force,
                fund_rule_version=body.fund_rule_version,
                valid_until=body.valid_until,
                input_versions=(trusted_version,),
                plan_reference=body.plan_reference,
                idempotency_key=_idempotency_key(request),
                request_hash=_request_hash(body),
                reference_price=trusted_price,
            )

        return await _respond(action, success_status=201)

    async def get_draft(request: Request) -> JSONResponse:
        async def action() -> object:
            owner_id = await _owner(owner_resolver, request)
            return await execution.get_draft(
                owner_id=owner_id,
                draft_id=request.path_params["draft_id"],
            )

        return await _respond(action)

    async def review_draft(request: Request) -> JSONResponse:
        async def action() -> object:
            body = await _body(request, ExpectedRevisionRequest)
            return await execution.review(
                owner_id=await _owner(owner_resolver, request),
                draft_id=request.path_params["draft_id"],
                expected_revision=body.expected_revision,
            )

        return await _respond(action)

    async def confirm_soft_risk(request: Request) -> JSONResponse:
        async def action() -> object:
            body = await _body(request, SoftRiskConfirmationRequest)
            return await execution.confirm_soft_risk(
                owner_id=await _owner(owner_resolver, request),
                draft_id=request.path_params["draft_id"],
                seen_reason_hash=body.seen_reason_hash,
            )

        return await _respond(action)

    async def confirm_draft(request: Request) -> JSONResponse:
        async def action() -> object:
            body = await _body(request, DraftConfirmationRequest)
            return await execution.confirm(
                owner_id=await _owner(owner_resolver, request),
                draft_id=request.path_params["draft_id"],
                expected_revision=body.expected_revision,
                seen_summary_hash=body.seen_summary_hash,
            )

        return await _respond(action)

    async def submit_draft(request: Request) -> JSONResponse:
        async def action() -> object:
            key = _idempotency_key(request)
            owner_id = await _owner(owner_resolver, request)
            stored = await execution.submit(
                owner_id=owner_id,
                draft_id=request.path_params["draft_id"],
                idempotency_key=key,
                request_hash=_request_hash(
                    {"draft_id": request.path_params["draft_id"]}
                ),
            )
            return await execution.get_order_view(
                owner_id=owner_id,
                order_id=stored.order_id,
            )

        return await _respond(action, success_status=201)

    async def list_orders(request: Request) -> JSONResponse:
        async def action() -> object:
            owner_id = await _owner(owner_resolver, request)
            return await execution.list_order_views(owner_id=owner_id)

        return await _respond(action)

    async def get_order(request: Request) -> JSONResponse:
        async def action() -> object:
            owner_id = await _owner(owner_resolver, request)
            return await execution.get_order_view(
                owner_id=owner_id,
                order_id=request.path_params["order_id"],
            )

        return await _respond(action)

    async def portfolio_positions(request: Request) -> JSONResponse:
        async def action() -> object:
            owner_id = await _owner(owner_resolver, request)
            return await portfolio.positions(owner_id=owner_id)

        return await _respond(action)

    async def decision_inbox_view(request: Request) -> JSONResponse:
        async def action() -> object:
            owner_id = await _owner(owner_resolver, request)
            return await decision_inbox.inbox(owner_id=owner_id)

        return await _respond(action)

    async def reconcile_order(request: Request) -> JSONResponse:
        async def action() -> object:
            owner_id = await _owner(owner_resolver, request)
            stored = await execution.reconcile(
                owner_id=owner_id,
                order_id=request.path_params["order_id"],
            )
            return await execution.get_order_view(
                owner_id=owner_id,
                order_id=stored.order_id,
            )

        return await _respond(action)

    async def cancel_order(request: Request) -> JSONResponse:
        async def action() -> object:
            owner_id = await _owner(owner_resolver, request)
            return await execution.cancel(
                owner_id=owner_id,
                order_id=request.path_params["order_id"],
            )

        return await _respond(action)

    async def list_fills(request: Request) -> JSONResponse:
        async def action() -> object:
            owner_id = await _owner(owner_resolver, request)
            return await execution.list_fills(
                owner_id=owner_id,
                order_id=request.query_params.get("order_id"),
            )

        return await _respond(action)

    return [
        Route("/accounts", create_account, methods=["POST"]),
        Route("/accounts/current", current_account, methods=["GET"]),
        Route(
            "/accounts/current/positions",
            current_positions,
            methods=["GET"],
        ),
        Route("/accounts/{account_id:str}/reset", reset_account, methods=["POST"]),
        Route("/drafts", create_draft, methods=["POST"]),
        Route("/drafts/{draft_id:str}", get_draft, methods=["GET"]),
        Route("/drafts/{draft_id:str}/review", review_draft, methods=["POST"]),
        Route(
            "/drafts/{draft_id:str}/soft-risk-confirmations",
            confirm_soft_risk,
            methods=["POST"],
        ),
        Route("/drafts/{draft_id:str}/confirm", confirm_draft, methods=["POST"]),
        Route("/drafts/{draft_id:str}/submit", submit_draft, methods=["POST"]),
        Route("/portfolio", portfolio_positions, methods=["GET"]),
        Route("/decision-inbox", decision_inbox_view, methods=["GET"]),
        Route("/orders", list_orders, methods=["GET"]),
        Route("/orders/{order_id:str}", get_order, methods=["GET"]),
        Route(
            "/orders/{order_id:str}/reconcile",
            reconcile_order,
            methods=["POST"],
        ),
        Route("/orders/{order_id:str}/cancel", cancel_order, methods=["POST"]),
        Route("/fills", list_fills, methods=["GET"]),
    ]


Model = TypeVar("Model", bound=APIModel)


async def _body(request: Request, model: type[Model]) -> Model:
    return model.model_validate(await request.json())


async def _owner(owner_resolver: OwnerResolver, request: Request) -> str:
    owner = (await owner_resolver(request)).strip()
    if not owner or len(owner) > 160:
        raise AuthenticationError("authenticated owner is required")
    return owner


def _idempotency_key(request: Request) -> str:
    key = request.headers.get(IDEMPOTENCY_HEADER, "").strip()
    if not key or len(key) > 160:
        raise ValueError(f"{IDEMPOTENCY_HEADER} is required")
    return key


def _request_hash(value: BaseModel | dict[str, object]) -> str:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


async def _respond(
    action: Callable[[], Awaitable[object]],
    *,
    success_status: int = 200,
) -> JSONResponse:
    try:
        result = await action()
        return JSONResponse(_json_value(result), status_code=success_status)
    except ExecutionFailure as error:
        return _error(error.code.value, str(error), 409)
    except ValidationError as error:
        return _error("VALIDATION_ERROR", str(error), 422)
    except AuthenticationError as error:
        return _error("UNAUTHORIZED", str(error), 401)
    except (LookupError, PermissionError) as error:
        return _error("NOT_FOUND", str(error), 404)
    except ConcurrentCommandConflict as error:
        return _error("REVISION_CONFLICT", str(error), 409)
    except DomainInvariantViolation as error:
        return _error("DOMAIN_INVARIANT_VIOLATION", str(error), 409)
    except (json.JSONDecodeError, ValueError) as error:
        return _error("INVALID_REQUEST", str(error), 400)
    except SimulationServiceUnavailable as error:
        return _error("SERVICE_UNAVAILABLE", str(error), 503)


def _json_value(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    return value


def _error(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message}},
        status_code=status,
    )
