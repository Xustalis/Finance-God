import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import create_access_token
from app.models.user import User


def test_register_login_and_me_expose_role(client: TestClient) -> None:
    registered = client.post(
        "/api/v1/auth/register",
        json={"email": "reader@example.com", "password": "correct-horse-123", "display_name": "Reader"},
    )

    assert registered.status_code == 201
    registration = registered.json()["data"]
    assert registration["access_token"]
    assert registration["token_type"] == "bearer"
    assert registration["user"]["role"] == "user"

    logged_in = client.post(
        "/api/v1/auth/login",
        json={"email": "reader@example.com", "password": "correct-horse-123"},
    )
    assert logged_in.status_code == 200
    token = logged_in.json()["data"]["access_token"]

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["data"]["email"] == "reader@example.com"
    assert me.json()["data"]["role"] == "user"


def test_me_rejects_token_for_missing_user(client: TestClient) -> None:
    token = create_access_token("00000000-0000-0000-0000-000000000099")

    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


def test_registration_validates_email_and_password(client: TestClient) -> None:
    bad_email = client.post(
        "/api/v1/auth/register",
        json={"email": "not-an-email", "password": "correct-horse-123"},
    )
    short_password = client.post(
        "/api/v1/auth/register",
        json={"email": "reader@example.com", "password": "short"},
    )

    assert bad_email.status_code == 422
    assert short_password.status_code == 422
    assert bad_email.json()["success"] is False
    assert bad_email.json()["error"]["code"] == "VALIDATION_ERROR"


def test_registration_unique_flush_conflict_returns_409(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def conflicting_flush(self, *args, **kwargs):
        raise IntegrityError("INSERT INTO users", {}, RuntimeError("duplicate email"))

    monkeypatch.setattr(AsyncSession, "flush", conflicting_flush)

    response = client.post(
        "/api/v1/auth/register",
        json={"email": "registration-race@example.com", "password": "correct-horse-123"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "HTTP_409"


@pytest.mark.asyncio
async def test_inactive_user_cannot_login(
    client: TestClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    registration = client.post(
        "/api/v1/auth/register",
        json={"email": "inactive@example.com", "password": "correct-horse-123"},
    ).json()["data"]
    async with session_factory() as session:
        user = await session.get(User, registration["user"]["id"])
        user.status = "inactive"
        await session.commit()

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "inactive@example.com", "password": "correct-horse-123"},
    )

    assert response.status_code == 401
