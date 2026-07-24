from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest
import server as finance_server
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from app.core.security import create_access_token
from app.models.user import User
from finance_god.api.simulation import SimulationAccountView, create_simulation_routes


class _Accounts:
    async def current(self, *, owner_id: str) -> SimulationAccountView:
        return SimulationAccountView(
            account_id=f"account-{owner_id}",
            owner_id=owner_id,
            status="active",
            cash_total_rmb=Decimal("100000"),
            cash_available_rmb=Decimal("100000"),
            cash_frozen_rmb=Decimal("0"),
            margin_rmb=Decimal("0"),
            revision=1,
        )


def _app() -> Starlette:
    return Starlette(
        routes=[
            Mount(
                "/api/simulation",
                routes=create_simulation_routes(
                    execution=object(),
                    accounts=_Accounts(),
                    portfolio=object(),
                    decision_inbox=object(),
                    owner_resolver=finance_server._authenticated_owner,
                ),
            )
        ]
    )


async def _create_user(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: str,
    email: str,
) -> None:
    async with session_factory() as session:
        session.add(
            User(
                id=user_id,
                email=email,
                hashed_password="unused-in-token-tests",
                status="active",
            )
        )
        await session.commit()


async def _set_user_status(
    session_factory: async_sessionmaker[AsyncSession],
    user_id: str,
    status: str,
) -> None:
    async with session_factory() as session:
        await session.execute(
            update(User).where(User.id == user_id).values(status=status)
        )
        await session.commit()


async def _delete_user(
    session_factory: async_sessionmaker[AsyncSession],
    user_id: str,
) -> None:
    async with session_factory() as session:
        await session.execute(delete(User).where(User.id == user_id))
        await session.commit()


def test_simulation_routes_use_active_jwt_subject_and_ignore_owner_header(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(finance_server, "create_db_session", session_factory)
    asyncio.run(
        _create_user(
            session_factory,
            user_id="user-a",
            email="simulation-user-a@example.com",
        )
    )
    asyncio.run(
        _create_user(
            session_factory,
            user_id="user-b",
            email="simulation-user-b@example.com",
        )
    )
    first_token = create_access_token("user-a")
    second_token = create_access_token("user-b")

    with TestClient(_app()) as client:
        first = client.get(
            "/api/simulation/accounts/current",
            headers={
                "Authorization": f"Bearer {first_token}",
                "x-finance-god-owner-id": "user-b",
            },
        )
        second = client.get(
            "/api/simulation/accounts/current",
            headers={"Authorization": f"Bearer {second_token}"},
        )

    assert first.status_code == 200
    assert first.json()["owner_id"] == "user-a"
    assert second.status_code == 200
    assert second.json()["owner_id"] == "user-b"


def test_simulation_routes_reject_missing_and_invalid_tokens(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(finance_server, "create_db_session", session_factory)

    with TestClient(_app()) as client:
        missing = client.get("/api/simulation/accounts/current")
        invalid = client.get(
            "/api/simulation/accounts/current",
            headers={"Authorization": "Bearer invalid"},
        )

    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "UNAUTHORIZED"
    assert invalid.status_code == 401
    assert invalid.json()["error"]["code"] == "UNAUTHORIZED"


def test_simulation_routes_reject_token_for_missing_user(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(finance_server, "create_db_session", session_factory)
    token = create_access_token("deleted-before-request")

    with TestClient(_app()) as client:
        response = client.get(
            "/api/simulation/accounts/current",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_simulation_routes_reject_existing_token_after_user_is_inactivated(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(finance_server, "create_db_session", session_factory)
    user_id = "inactive-after-token"
    asyncio.run(
        _create_user(
            session_factory,
            user_id=user_id,
            email="inactive-after-token@example.com",
        )
    )
    token = create_access_token(user_id)
    asyncio.run(_set_user_status(session_factory, user_id, "inactive"))

    with TestClient(_app()) as client:
        response = client.get(
            "/api/simulation/accounts/current",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_simulation_routes_reject_existing_token_after_user_is_deleted(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(finance_server, "create_db_session", session_factory)
    user_id = "deleted-after-token"
    asyncio.run(
        _create_user(
            session_factory,
            user_id=user_id,
            email="deleted-after-token@example.com",
        )
    )
    token = create_access_token(user_id)
    asyncio.run(_delete_user(session_factory, user_id))

    with TestClient(_app()) as client:
        response = client.get(
            "/api/simulation/accounts/current",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
