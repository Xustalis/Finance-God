"""Authenticated durable server-sent event stream."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from finance_god.api.auth import AuthenticationError, OwnerResolver
from finance_god.infrastructure.persistence.workspace_models import (
    NotificationDeliveryRow,
    UserEventRow,
)


def create_event_routes(
    *,
    session_factory: Callable[[], AsyncSession],
    owner_resolver: OwnerResolver,
    heartbeat_seconds: float = 15.0,
    poll_seconds: float = 1.0,
) -> list[Route]:
    async def events(request: Request):
        try:
            owner_id = await owner_resolver(request)
            cursor = _cursor(request)
            async with session_factory() as session:
                minimum, maximum = (
                    await session.execute(
                        select(
                            func.min(UserEventRow.cursor),
                            func.max(UserEventRow.cursor),
                        ).where(UserEventRow.owner_user_id == owner_id)
                    )
                ).one()
            if cursor is not None and minimum is not None and cursor < minimum - 1:
                return JSONResponse(
                    {
                        "error": {
                            "code": "EVENT_CURSOR_EXPIRED",
                            "message": "事件游标已过期，请通过提醒历史重新同步。",
                        }
                    },
                    status_code=409,
                )
            if cursor is not None and maximum is not None and cursor > maximum:
                return JSONResponse(
                    {
                        "error": {
                            "code": "INVALID_EVENT_CURSOR",
                            "message": "事件游标超出当前用户事件范围。",
                        }
                    },
                    status_code=400,
                )
            return StreamingResponse(
                _stream(
                    request,
                    session_factory,
                    owner_id,
                    cursor or 0,
                    heartbeat_seconds,
                    poll_seconds,
                ),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache, no-transform",
                    "X-Accel-Buffering": "no",
                },
            )
        except AuthenticationError as error:
            return JSONResponse(
                {"error": {"code": "UNAUTHORIZED", "message": str(error)}},
                status_code=401,
            )
        except ValueError as error:
            return JSONResponse(
                {"error": {"code": "INVALID_EVENT_CURSOR", "message": str(error)}},
                status_code=400,
            )

    return [Route("/events", events, methods=["GET"])]


def _cursor(request: Request) -> int | None:
    raw = request.query_params.get("cursor") or request.headers.get("last-event-id")
    if raw is None or not raw.strip():
        return None
    try:
        cursor = int(raw)
    except ValueError as error:
        raise ValueError("事件游标必须为非负整数。") from error
    if cursor < 0:
        raise ValueError("事件游标必须为非负整数。")
    return cursor


async def _stream(
    request: Request,
    session_factory: Callable[[], AsyncSession],
    owner_id: str,
    cursor: int,
    heartbeat_seconds: float,
    poll_seconds: float,
) -> AsyncIterator[bytes]:
    last_heartbeat = asyncio.get_running_loop().time()
    yield b": connected\n\n"
    while not await request.is_disconnected():
        async with session_factory() as session:
            rows = list(
                await session.scalars(
                    select(UserEventRow)
                    .where(
                        UserEventRow.owner_user_id == owner_id,
                        UserEventRow.cursor > cursor,
                    )
                    .order_by(UserEventRow.cursor)
                    .limit(100)
                )
            )
            for row in rows:
                data = {
                    "event_id": row.event_id,
                    "cursor": str(row.cursor),
                    "event_type": row.event_type,
                    "occurred_at": row.occurred_at.isoformat(),
                    "notification_id": row.notification_id,
                    "fact_version": row.fact_version,
                    "payload": row.payload_json,
                }
                yield (
                    f"id: {row.cursor}\n"
                    f"event: {row.event_type}\n"
                    f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                ).encode()
                cursor = row.cursor
                await session.execute(
                    update(NotificationDeliveryRow)
                    .where(
                        NotificationDeliveryRow.notification_id
                        == row.notification_id,
                        NotificationDeliveryRow.channel == "in_app",
                    )
                    .values(
                        attempt=NotificationDeliveryRow.attempt + 1,
                        status="delivered",
                        delivered_at=row.occurred_at,
                        error=None,
                    )
                )
            if rows:
                await session.commit()
        now = asyncio.get_running_loop().time()
        if now - last_heartbeat >= heartbeat_seconds:
            yield b": heartbeat\n\n"
            last_heartbeat = now
        await asyncio.sleep(poll_seconds)
