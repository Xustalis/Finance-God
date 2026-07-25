from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol, TypeVar

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from finance_god.api.auth import AuthenticationError, OwnerResolver
from finance_god.application.decision_inbox import DecisionInboxService
from finance_god.application.idempotency import canonical_request_hash
from finance_god.application.portfolio_query import PortfolioQueryService
from finance_god.application.simulation_clock import (
    SimulationClockService,
    SimulationClockView,
)
from finance_god.domain import (
    ConcurrentCommandConflict,
    DomainInvariantViolation,
    IdempotencyConflict,
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
from finance_god.trade_review import TradeReviewService

IDEMPOTENCY_HEADER = "idempotency-key"
MarketReferenceProvider = Callable[
    [str],
    Awaitable[tuple[Decimal, VersionReference]],
]
HistoricalMarketReferenceProvider = Callable[
    [str, str],
    Awaitable[tuple[Decimal, VersionReference]],
]
HistoricalMarketBarsProvider = Callable[
    [str, str, str],
    Awaitable[dict[str, object]],
]
SimulationStartValidator = Callable[[AwareDatetime], Awaitable[None]]


class SimulationServiceUnavailable(RuntimeError):
    """A required server-side simulation dependency is not available."""


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SimulationAccountCreate(APIModel):
    initial_cash_rmb: Decimal = Field(gt=0)
    simulation_start_at: AwareDatetime


class SimulationAccountReset(APIModel):
    initial_cash_rmb: Decimal = Field(gt=0)
    simulation_start_at: AwareDatetime


class SimulationAccountView(APIModel):
    account_id: str
    owner_id: str
    status: str
    cash_total_rmb: Decimal
    cash_available_rmb: Decimal
    cash_frozen_rmb: Decimal
    margin_rmb: Decimal
    revision: int = Field(ge=1)
    simulation_time: AwareDatetime | None = None


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


class ImmediateMarketOrderRequest(APIModel):
    account_id: str = Field(min_length=1, max_length=160)
    instrument_id: str = Field(min_length=1, max_length=160)
    side: OrderSide
    quantity: Decimal = Field(gt=0)
    market_mode: Literal["live", "historical"] = "live"


class ProtectiveStrategyCreateRequest(APIModel):
    account_id: str = Field(min_length=1, max_length=160)
    instrument_id: str = Field(min_length=1, max_length=160)
    quantity: Decimal = Field(gt=0)
    take_profit_price: Decimal | None = Field(default=None, gt=0)
    stop_loss_price: Decimal | None = Field(default=None, gt=0)


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
    simulation_clock: SimulationClockService | None = None,
    market_reference_provider: MarketReferenceProvider | None = None,
    historical_market_reference_provider: HistoricalMarketReferenceProvider | None = None,
    historical_market_bars_provider: HistoricalMarketBarsProvider | None = None,
    simulation_start_validator: SimulationStartValidator | None = None,
    trade_review_service: TradeReviewService | None = None,
) -> list[Route]:
    async def create_account(request: Request) -> JSONResponse:
        async def action() -> object:
            body = await _body(request, SimulationAccountCreate)
            if simulation_start_validator is not None:
                await simulation_start_validator(body.simulation_start_at)
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
            if simulation_start_validator is not None:
                await simulation_start_validator(body.simulation_start_at)
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

    async def current_clock(request: Request) -> JSONResponse:
        async def action() -> SimulationClockView:
            if simulation_clock is None:
                raise SimulationServiceUnavailable("simulation clock is unavailable")
            return await simulation_clock.current_for_owner(
                await _owner(owner_resolver, request)
            )

        return await _respond(action)

    async def resume_clock(request: Request) -> JSONResponse:
        async def action() -> SimulationClockView:
            if simulation_clock is None:
                raise SimulationServiceUnavailable("simulation clock is unavailable")
            body = await _body(request, ExpectedRevisionRequest)
            return await simulation_clock.resume_next_session(
                await _owner(owner_resolver, request),
                expected_revision=body.expected_revision,
                idempotency_key=_idempotency_key(request),
            )

        return await _respond(action)

    async def current_positions(request: Request) -> JSONResponse:
        async def action() -> object:
            owner_id = await _owner(owner_resolver, request)
            return await accounts.positions(owner_id=owner_id)

        return await _respond(action)

    async def historical_overview(request: Request) -> JSONResponse:
        async def action() -> object:
            if historical_market_bars_provider is None:
                raise SimulationServiceUnavailable("historical market data is unavailable")
            owner_id = await _owner(owner_resolver, request)
            symbols = tuple(
                item.strip().upper()
                for item in request.query_params.get("symbols", "").split(",")
                if item.strip()
            )
            quotes = []
            warnings = []
            for symbol in symbols:
                try:
                    result = await historical_market_bars_provider(owner_id, symbol, "1m")
                except Exception:  # noqa: BLE001 - isolate batch items
                    warnings.append(
                        {
                            "code": "HISTORICAL_MARKET_DATA_UNAVAILABLE",
                            "symbol": symbol,
                            "message": (
                                "该标的在当前模拟时点没有可展示的 "
                                "PandaData 分钟行情"
                            ),
                        }
                    )
                    continue
                bars = result["bars"]
                if not isinstance(bars, tuple) or not bars:
                    warnings.append(
                        {
                            "code": "HISTORICAL_MARKET_DATA_EMPTY",
                            "symbol": symbol,
                            "message": "PandaData returned no completed minute bar",
                        }
                    )
                    continue
                latest = bars[-1]
                previous = bars[-2] if len(bars) > 1 else None
                change = latest.close - previous.close if previous is not None else None
                quotes.append(
                    {
                        "symbol": symbol,
                        "name": symbol,
                        "last": latest.close,
                        "change": change,
                        "change_percent": (
                            change / previous.close
                            if change is not None and previous is not None and previous.close
                            else None
                        ),
                        "provider": "PandaData",
                        "provider_time": latest.provider_time,
                        "frequency": "1m",
                        "freshness": latest.freshness,
                        "market_status": "in_session",
                        "simulation_clock_revision": result[
                            "simulation_clock_revision"
                        ],
                    }
                )
            return {"data": {"quotes": quotes}, "warnings": warnings}

        return await _respond(action)

    async def historical_bars(request: Request) -> JSONResponse:
        async def action() -> object:
            if historical_market_bars_provider is None:
                raise SimulationServiceUnavailable("historical market data is unavailable")
            symbol = request.query_params.get("symbol", "").strip().upper()
            if not symbol:
                raise ValueError("symbol is required")
            frequency = request.query_params.get("frequency", "1m").strip().lower()
            if frequency not in {"1m", "daily"}:
                raise ValueError("frequency must be 1m or daily")
            try:
                result = await historical_market_bars_provider(
                    await _owner(owner_resolver, request),
                    symbol,
                    frequency,
                )
            except SimulationServiceUnavailable:
                raise
            except Exception as error:
                raise SimulationServiceUnavailable(
                    "当前模拟时点没有可展示的 PandaData K 线"
                ) from error
            return result

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

    async def create_immediate_market_order(request: Request) -> JSONResponse:
        async def action() -> object:
            body = await _body(request, ImmediateMarketOrderRequest)
            if body.side not in {OrderSide.BUY, OrderSide.SELL}:
                raise ValueError("immediate market order only supports buy or sell")
            owner_id = await _owner(owner_resolver, request)
            if body.market_mode == "historical":
                if historical_market_reference_provider is None:
                    raise SimulationServiceUnavailable(
                        "trusted historical market reference provider is unavailable"
                    )
                trusted_price, trusted_version = (
                    await historical_market_reference_provider(
                        owner_id, body.instrument_id
                    )
                )
            else:
                if market_reference_provider is None:
                    raise SimulationServiceUnavailable(
                        "trusted live market reference provider is unavailable"
                    )
                trusted_price, trusted_version = await market_reference_provider(
                    body.instrument_id
                )
            business_time = None
            if body.market_mode == "historical":
                if simulation_clock is None:
                    raise SimulationServiceUnavailable(
                        "simulation clock is unavailable in historical mode"
                    )
                business_time = await simulation_clock.current_for_owner(owner_id)
            execution_args = dict(
                owner_id=owner_id,
                account_id=body.account_id,
                instrument_id=body.instrument_id,
                side=body.side,
                quantity=body.quantity,
                trusted_price=trusted_price,
                market_evidence=trusted_version,
                idempotency_key=_idempotency_key(request),
                request_hash=_request_hash(body),
            )
            if business_time is not None:
                execution_args["business_time"] = business_time.current_time
            order = await execution.execute_immediate_market_order(**execution_args)
            if trade_review_service is None or order.status != "filled":
                return order
            positions = await accounts.positions(owner_id=owner_id)
            position = next(
                (
                    item
                    for item in positions
                    if item.account_id == body.account_id
                    and item.instrument_id == body.instrument_id
                ),
                None,
            )
            journal = await trade_review_service.record_filled_order(
                owner_id=owner_id,
                account_id=body.account_id,
                order=order,
                market_evidence=trusted_version.model_dump(mode="json"),
                position_quantity_after=(
                    position.long_quantity if position is not None else Decimal("0")
                ),
                profile_version=None,
            )
            return {**order.model_dump(mode="json"), **journal}

        return await _respond(action, success_status=201)

    async def create_protective_strategy(request: Request) -> JSONResponse:
        async def action() -> object:
            body = await _body(request, ProtectiveStrategyCreateRequest)
            owner_id = await _owner(owner_resolver, request)
            positions = await accounts.positions(owner_id=owner_id)
            position = next(
                (
                    item
                    for item in positions
                    if item.account_id == body.account_id
                    and item.instrument_id == body.instrument_id
                ),
                None,
            )
            available = (
                position.settled_quantity - position.frozen_quantity
                if position is not None
                else Decimal("0")
            )
            if body.quantity > available:
                raise ValueError("protective strategy quantity exceeds available position")
            if market_reference_provider is None:
                raise SimulationServiceUnavailable(
                    "trusted market reference provider is unavailable"
                )
            trusted_price, _trusted_version = await market_reference_provider(
                body.instrument_id
            )
            return await execution.create_protective_strategy(
                owner_id=owner_id,
                account_id=body.account_id,
                instrument_id=body.instrument_id,
                quantity=body.quantity,
                take_profit_price=body.take_profit_price,
                stop_loss_price=body.stop_loss_price,
                reference_price=trusted_price,
                idempotency_key=_idempotency_key(request),
                request_hash=_request_hash(body),
            )

        return await _respond(action, success_status=201)

    async def list_protective_strategies(request: Request) -> JSONResponse:
        async def action() -> object:
            return await execution.list_protective_strategies(
                owner_id=await _owner(owner_resolver, request)
            )

        return await _respond(action)

    async def cancel_protective_strategy(request: Request) -> JSONResponse:
        async def action() -> object:
            return await execution.cancel_protective_strategy(
                owner_id=await _owner(owner_resolver, request),
                strategy_id=request.path_params["strategy_id"],
                idempotency_key=_idempotency_key(request),
                request_hash=_request_hash(
                    {"strategy_id": request.path_params["strategy_id"]}
                ),
            )

        return await _respond(action)

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
                idempotency_key=_idempotency_key(request),
                request_hash=_request_hash(
                    {
                        "draft_id": request.path_params["draft_id"],
                        **body.model_dump(mode="json"),
                    }
                ),
            )

        return await _respond(action)

    async def confirm_soft_risk(request: Request) -> JSONResponse:
        async def action() -> object:
            body = await _body(request, SoftRiskConfirmationRequest)
            return await execution.confirm_soft_risk(
                owner_id=await _owner(owner_resolver, request),
                draft_id=request.path_params["draft_id"],
                seen_reason_hash=body.seen_reason_hash,
                idempotency_key=_idempotency_key(request),
                request_hash=_request_hash(
                    {
                        "draft_id": request.path_params["draft_id"],
                        **body.model_dump(mode="json"),
                    }
                ),
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
                idempotency_key=_idempotency_key(request),
                request_hash=_request_hash(
                    {
                        "draft_id": request.path_params["draft_id"],
                        **body.model_dump(mode="json"),
                    }
                ),
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
                idempotency_key=_idempotency_key(request),
                request_hash=_request_hash(
                    {"order_id": request.path_params["order_id"]}
                ),
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
                idempotency_key=_idempotency_key(request),
                request_hash=_request_hash(
                    {"order_id": request.path_params["order_id"]}
                ),
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
        Route("/clock", current_clock, methods=["GET"]),
        Route("/clock/resume-next-session", resume_clock, methods=["POST"]),
        Route("/market/overview", historical_overview, methods=["GET"]),
        Route("/market/bars", historical_bars, methods=["GET"]),
        Route(
            "/accounts/current/positions",
            current_positions,
            methods=["GET"],
        ),
        Route("/accounts/{account_id:str}/reset", reset_account, methods=["POST"]),
        Route("/drafts", create_draft, methods=["POST"]),
        Route("/market-orders", create_immediate_market_order, methods=["POST"]),
        Route(
            "/protective-strategies",
            create_protective_strategy,
            methods=["POST"],
        ),
        Route(
            "/protective-strategies",
            list_protective_strategies,
            methods=["GET"],
        ),
        Route(
            "/protective-strategies/{strategy_id:str}/cancel",
            cancel_protective_strategy,
            methods=["POST"],
        ),
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
    return canonical_request_hash(payload)


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
    except IdempotencyConflict as error:
        return _error("IDEMPOTENCY_CONFLICT", str(error), 409)
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
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def _error(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message}},
        status_code=status,
    )
