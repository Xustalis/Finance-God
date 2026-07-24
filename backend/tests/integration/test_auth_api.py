import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import create_access_token, hash_password
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


def test_patch_me_persists_account_profile(client: TestClient) -> None:
    registration = client.post(
        "/api/v1/auth/register",
        json={"email": "profile-edit@example.com", "password": "correct-horse-123", "display_name": "Old"},
    ).json()["data"]
    token = registration["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    patched = client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={"display_name": "新昵称", "base_currency": "USD", "region": "US"},
    )

    assert patched.status_code == 200
    data = patched.json()["data"]
    assert data["display_name"] == "新昵称"
    assert data["base_currency"] == "USD"
    assert data["region"] == "US"

    # 变更已落库：重新拉取 /me 返回持久化后的值
    refetched = client.get("/api/v1/auth/me", headers=headers).json()["data"]
    assert refetched["display_name"] == "新昵称"
    assert refetched["base_currency"] == "USD"
    assert refetched["region"] == "US"


def test_patch_me_clears_display_name_with_blank(client: TestClient) -> None:
    registration = client.post(
        "/api/v1/auth/register",
        json={"email": "profile-clear@example.com", "password": "correct-horse-123", "display_name": "有值"},
    ).json()["data"]
    headers = {"Authorization": f"Bearer {registration['access_token']}"}

    patched = client.patch("/api/v1/auth/me", headers=headers, json={"display_name": "   "})

    assert patched.status_code == 200
    assert patched.json()["data"]["display_name"] is None


def test_patch_me_rejects_invalid_currency(client: TestClient) -> None:
    registration = client.post(
        "/api/v1/auth/register",
        json={"email": "profile-invalid@example.com", "password": "correct-horse-123"},
    ).json()["data"]
    headers = {"Authorization": f"Bearer {registration['access_token']}"}

    response = client.patch("/api/v1/auth/me", headers=headers, json={"base_currency": "cny"})

    assert response.status_code == 422
    assert response.json()["success"] is False


def test_patch_me_requires_authentication(client: TestClient) -> None:
    response = client.patch("/api/v1/auth/me", json={"display_name": "匿名"})

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_admin_login_accepts_only_active_admins(
    client: TestClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        session.add(
            User(
                email="admin@example.com",
                hashed_password=hash_password("correct-horse-123"),
                role="admin",
                status="active",
            )
        )
        await session.commit()

    response = client.post(
        "/api/v1/auth/admin/login",
        json={"email": "admin@example.com", "password": "correct-horse-123"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["user"]["role"] == "admin"


def test_admin_login_rejects_normal_user_without_account_disclosure(client: TestClient) -> None:
    client.post(
        "/api/v1/auth/register",
        json={"email": "reader-admin-check@example.com", "password": "correct-horse-123"},
    )

    response = client.post(
        "/api/v1/auth/admin/login",
        json={"email": "reader-admin-check@example.com", "password": "correct-horse-123"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["message"] == "管理员邮箱或密码错误"


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
