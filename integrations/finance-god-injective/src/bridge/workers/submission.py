from __future__ import annotations

import asyncio
import logging

from bridge.application import BridgeApplication
from bridge.persistence.uow import AsyncUnitOfWork

LOGGER = logging.getLogger(__name__)


async def submit_confirmed_plan(app: BridgeApplication, session_factory, plan_id: str) -> None:
    """Serialized persistence claim prevents duplicate worker broadcasts."""
    async with AsyncUnitOfWork(session_factory) as uow:
        assert uow.repository is not None
        await app.submit(uow.repository, plan_id)
        await uow.commit()


async def reconcile_active_order(
    app: BridgeApplication,
    session_factory,
    order_id: str,
) -> None:
    async with AsyncUnitOfWork(session_factory) as uow:
        assert uow.repository is not None
        await app.reconcile(uow.repository, order_id)
        await uow.commit()


async def run_bridge_workers(
    app: BridgeApplication,
    session_factory,
    stop: asyncio.Event,
    wakeup: asyncio.Event,
) -> None:
    """Recover confirmed plans and reconcile active orders until shutdown."""
    while not stop.is_set():
        async with AsyncUnitOfWork(session_factory) as uow:
            assert uow.repository is not None
            confirmed_ids = [
                item.id for item in await uow.repository.list_confirmed_plans(limit=20)
            ]
            active_ids = [item.id for item in await uow.repository.list_active_orders(limit=100)]
        for plan_id in confirmed_ids:
            try:
                await submit_confirmed_plan(app, session_factory, plan_id)
            except Exception:
                LOGGER.exception("confirmed Testnet plan submission failed plan_id=%s", plan_id)
        for order_id in active_ids:
            try:
                await reconcile_active_order(app, session_factory, order_id)
            except Exception:
                LOGGER.exception("Testnet order reconciliation failed order_id=%s", order_id)
        try:
            await asyncio.wait_for(
                wakeup.wait(),
                timeout=app.settings.reconciliation_interval_seconds,
            )
        except TimeoutError:
            pass
        wakeup.clear()
