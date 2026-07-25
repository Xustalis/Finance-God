from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from bridge.api.routes import router
from bridge.application import BridgeApplication
from bridge.finance_god import FinanceGodClient
from bridge.injective.client import InjectiveClient
from bridge.persistence.database import create_engine, create_session_factory
from bridge.persistence.models import Base
from bridge.settings import Settings, get_settings
from bridge.workers import run_bridge_workers


def create_app(
    *,
    settings: Settings | None = None,
    injective: Any | None = None,
    finance_god: Any | None = None,
) -> FastAPI:
    configured = settings or get_settings()
    engine = create_engine(configured.database_url)
    factory = create_session_factory(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime_injective = injective
        if runtime_injective is None:
            key = (
                configured.private_key_hex.get_secret_value()
                if configured.execution_enabled and configured.private_key_hex
                else None
            )
            runtime_injective = InjectiveClient.from_sdk(
                network=configured.network,
                private_key_hex=key,
                subaccount_index=configured.subaccount_index,
            )
        runtime_finance_god = finance_god
        if runtime_finance_god is None and configured.finance_god_sync_enabled:
            assert configured.finance_god_read_token is not None
            runtime_finance_god = FinanceGodClient(
                configured.finance_god_base_url,
                configured.finance_god_read_token.get_secret_value(),
            )
        bridge = BridgeApplication(configured, runtime_injective, runtime_finance_god)
        app.state.bridge = bridge
        if configured.auto_create_schema:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
        stop = asyncio.Event()
        wakeup = asyncio.Event()
        app.state.submission_wakeup = wakeup
        worker = asyncio.create_task(
            run_bridge_workers(bridge, factory, stop, wakeup),
            name="injective-bridge-workers",
        )
        try:
            yield
        finally:
            stop.set()
            wakeup.set()
            await worker
            await engine.dispose()
            close = getattr(runtime_injective, "close", None)
            if close is not None:
                await close()

    app = FastAPI(title=configured.app_name, lifespan=lifespan)
    app.state.session_factory = factory
    app.dependency_overrides[get_settings] = lambda: configured
    app.include_router(router)
    return app


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run("bridge.main:app", host="0.0.0.0", port=8080)
