from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from bridge.api.auth import require_admin, require_idempotency_key
from bridge.api.schemas import PlanConfirm, PlanCreate, SourceSnapshotCreate
from bridge.application import BridgeApplication, _model
from bridge.persistence.repository import (
    IdempotencyConflictError,
    RecordNotFoundError,
    RevisionConflictError,
    canonical_json_hash,
)
from bridge.persistence.uow import AsyncUnitOfWork

router = APIRouter()


def _app(request: Request) -> BridgeApplication:
    return request.app.state.bridge


def _factory(request: Request):
    return request.app.state.session_factory


async def _write(
    request: Request,
    operation: str,
    key: str,
    request_payload: Mapping[str, object],
    action,
    *,
    success_code: int = 200,
):
    factory = _factory(request)
    async with AsyncUnitOfWork(factory) as uow:
        assert uow.repository is not None
        try:
            record, fresh = await uow.repository.reserve_idempotency(
                operation=operation,
                idempotency_key=key,
                request_hash=canonical_json_hash(request_payload),
            )
        except IdempotencyConflictError as exc:
            raise HTTPException(
                409, detail={"code": "IDEMPOTENCY_CONFLICT", "message": str(exc)}
            ) from exc
        if not fresh:
            if record.response_body is None:
                raise HTTPException(
                    409,
                    detail={"code": "IDEMPOTENCY_IN_PROGRESS", "message": "request is in progress"},
                )
            return record.response_code or 200, record.response_body, False
        try:
            result = await action(uow.repository)
            await uow.repository.complete_idempotency(
                record.id,
                response_code=success_code,
                response_body=result,
            )
            await uow.commit()
            return success_code, result, True
        except Exception as exc:
            detail = _error(exc)
            await uow.repository.fail_idempotency(
                record.id,
                response_code=detail.status_code,
                response_body=detail.detail,
            )
            await uow.commit()
            raise detail from exc


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, RecordNotFoundError):
        return HTTPException(404, detail={"error": {"code": "NOT_FOUND", "message": str(exc)}})
    if isinstance(exc, RevisionConflictError):
        return HTTPException(
            409, detail={"error": {"code": "REVISION_CONFLICT", "message": str(exc)}}
        )
    return HTTPException(400, detail={"error": {"code": "REQUEST_FAILED", "message": str(exc)}})


@router.get("/live")
async def live():
    return {"status": "live"}


@router.get("/ready")
async def ready(request: Request):
    try:
        async with _factory(request)() as session:
            await session.execute(text("SELECT 1"))
        detail = await _app(request).ready()
    except Exception as exc:
        raise HTTPException(
            503, detail={"error": {"code": "NOT_READY", "message": str(exc)}}
        ) from exc
    return {"status": "ready", "database": "ready", **detail}


@router.post("/v1/source-snapshots/finance-god", dependencies=[Depends(require_admin)])
async def source_snapshot(
    request: Request,
    payload: SourceSnapshotCreate,
    key: Annotated[str, Depends(require_idempotency_key)],
):
    code, body, _ = await _write(
        request,
        "source_snapshot",
        key,
        payload.model_dump(mode="json"),
        lambda repo: _app(request).source_snapshot(repo, payload.plan_id),
        success_code=201,
    )
    return JSONResponse(status_code=code, content=body)


@router.post("/v1/plans", dependencies=[Depends(require_admin)])
async def create_plan(
    request: Request, payload: PlanCreate, key: Annotated[str, Depends(require_idempotency_key)]
):
    code, body, _ = await _write(
        request,
        "create_plan",
        key,
        payload.model_dump(mode="json"),
        lambda repo: _app(request).create_plan(
            repo,
            side=payload.side,
            price=payload.price,
            quantity=payload.quantity,
            source_snapshot_id=payload.source_snapshot_id,
        ),
        success_code=201,
    )
    return JSONResponse(status_code=code, content=body)


@router.post("/v1/plans/{plan_id}/review", dependencies=[Depends(require_admin)])
async def review_plan(
    request: Request, plan_id: str, key: Annotated[str, Depends(require_idempotency_key)]
):
    code, body, _ = await _write(
        request,
        f"review:{plan_id}",
        key,
        {"plan_id": plan_id},
        lambda repo: _app(request).review(repo, plan_id),
    )
    return JSONResponse(status_code=code, content=body)


@router.post("/v1/plans/{plan_id}/confirm", dependencies=[Depends(require_admin)])
async def confirm_plan(
    request: Request,
    plan_id: str,
    payload: PlanConfirm,
    key: Annotated[str, Depends(require_idempotency_key)],
):
    code, body, fresh = await _write(
        request,
        f"confirm:{plan_id}",
        key,
        {"plan_id": plan_id, **payload.model_dump(mode="json")},
        lambda repo: _app(request).confirm(repo, plan_id, payload.expected_revision),
    )
    if fresh:
        request.app.state.submission_wakeup.set()
    return JSONResponse(status_code=code, content=body)


@router.get("/v1/plans/{plan_id}")
async def get_plan(request: Request, plan_id: str):
    async with AsyncUnitOfWork(_factory(request)) as uow:
        assert uow.repository is not None
        try:
            plan = await uow.repository.get_plan(plan_id)
            order = await uow.repository.find_order_by_plan(plan_id)
            return {
                "plan": _model(plan),
                "order": _model(order) if order is not None else None,
            }
        except Exception as exc:
            raise _error(exc) from exc


@router.get("/v1/orders/{order_id}")
async def get_order(request: Request, order_id: str):
    async with AsyncUnitOfWork(_factory(request)) as uow:
        assert uow.repository is not None
        try:
            return _model(await uow.repository.get_order(order_id))
        except Exception as exc:
            raise _error(exc) from exc


@router.post("/v1/orders/{order_id}/cancel", dependencies=[Depends(require_admin)])
async def cancel_order(
    request: Request, order_id: str, key: Annotated[str, Depends(require_idempotency_key)]
):
    code, body, _ = await _write(
        request,
        f"cancel:{order_id}",
        key,
        {"order_id": order_id},
        lambda repo: _app(request).cancel(repo, order_id),
    )
    return JSONResponse(status_code=code, content=body)
