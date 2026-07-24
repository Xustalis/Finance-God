"""Serve the Finance-God desktop prototype and normalized PandaData APIs."""

from __future__ import annotations

import asyncio
from pathlib import Path
from threading import Lock
from uuid import uuid4

from dotenv import load_dotenv
from finance_god.market_data import (
    MarketDataError,
    MarketDataService,
    QuoteCoordinator,
)
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket

_BACKEND_ROOT = Path(__file__).resolve().parent
_PROJECT_ROOT = _BACKEND_ROOT.parent
load_dotenv(_BACKEND_ROOT / ".env", override=False)

market_data: MarketDataService | None = None
quote_coordinator: QuoteCoordinator | None = None
_service_lock = Lock()


def _services() -> tuple[MarketDataService, QuoteCoordinator]:
    global market_data, quote_coordinator
    if market_data is not None and quote_coordinator is not None:
        return market_data, quote_coordinator
    with _service_lock:
        if market_data is None:
            market_data = MarketDataService.from_environment()
        if quote_coordinator is None:
            quote_coordinator = QuoteCoordinator(market_data)
    return market_data, quote_coordinator


def _json(model: object, *, status_code: int = 200) -> JSONResponse:
    if hasattr(model, "model_dump"):
        payload = model.model_dump(mode="json")
    else:
        payload = model
    return JSONResponse(payload, status_code=status_code)


async def health(_: Request) -> JSONResponse:
    try:
        service, _coordinator = _services()
        ready, reason = await asyncio.to_thread(service.probe_readiness)
    except MarketDataError as error:
        ready, reason = False, error.public_code.value
    except Exception:  # noqa: BLE001 - readiness must remain a safe boundary
        ready, reason = False, "MARKET_DATA_INTERNAL_ERROR"
    return _json(
        {
            "liveness": "live",
            "readiness": "ready" if ready else "not_ready",
            "readiness_reason": reason,
            "market_data": "PandaData",
            "account_mode": "simulation",
        },
        status_code=200 if ready else 503,
    )


async def quotes(request: Request) -> JSONResponse:
    symbols = request.query_params.get("symbols", "").split(",")
    try:
        _, coordinator = _services()
        result = await coordinator.get(symbols)
    except (ValueError, ValidationError):
        return _safe_error(
            code="MARKET_DATA_INVALID_REQUEST",
            message="The market-data request is invalid.",
            status_code=400,
        )
    except MarketDataError as error:
        return _json({"error": error.public_payload()}, status_code=502)
    except Exception:  # noqa: BLE001 - public HTTP error boundary
        return _internal_error()
    status_code = 200 if result.quotes else 502
    return _json(result, status_code=status_code)


async def bars(request: Request) -> JSONResponse:
    symbol = request.query_params.get("symbol", "")
    try:
        limit = int(request.query_params.get("limit", "80"))
        service, _ = _services()
        frequency, items = await asyncio.to_thread(
            service.fetch_bars,
            symbol,
            limit=limit,
        )
    except (ValueError, ValidationError):
        return _safe_error(
            code="MARKET_DATA_INVALID_REQUEST",
            message="The market-data request is invalid.",
            status_code=400,
        )
    except MarketDataError as error:
        return _json({"error": error.public_payload()}, status_code=502)
    except Exception:  # noqa: BLE001 - public HTTP error boundary
        return _internal_error()
    return _json(
        {
            "provider": "PandaData",
            "symbol": symbol.upper(),
            "frequency": frequency,
            "bars": [item.model_dump(mode="json") for item in items],
        }
    )


async def catalog(_request: Request) -> JSONResponse:
    try:
        service, _coordinator = _services()
        items = await asyncio.to_thread(service.catalog)
    except MarketDataError as error:
        return _json({"error": error.public_payload()}, status_code=502)
    except Exception:  # noqa: BLE001 - public HTTP error boundary
        return _internal_error()
    return _json({"provider": "PandaData", "datasets": items})


def _safe_error(
    *,
    code: str,
    message: str,
    status_code: int,
) -> JSONResponse:
    return _json(
        {
            "error": {
                "code": code,
                "message": message,
                "trace_id": uuid4().hex,
            }
        },
        status_code=status_code,
    )


def _internal_error() -> JSONResponse:
    return _safe_error(
        code="MARKET_DATA_INTERNAL_ERROR",
        message="The market-data request failed internally.",
        status_code=500,
    )


async def reject_websocket(websocket: WebSocket) -> None:
    """Reject unsupported upgrade probes before they reach StaticFiles."""
    await websocket.close(code=1008, reason="Finance-God prototype uses HTTP polling")


routes = [
    Route("/api/health", health),
    Route("/api/market/quotes", quotes),
    Route("/api/market/bars", bars),
    Route("/api/market/catalog", catalog),
    WebSocketRoute("/{path:path}", reject_websocket),
    Mount(
        "/",
        app=StaticFiles(directory=_PROJECT_ROOT / "prototype", html=True),
        name="prototype",
    ),
]

app = Starlette(debug=False, routes=routes)
