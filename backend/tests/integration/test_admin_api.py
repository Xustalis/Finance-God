import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.ai_config import AIModelConfig, AdminAuditRecord, PromptVersion
from app.models.user import User
from app.config import settings


def register(client: TestClient, email: str) -> tuple[str, str]:
    data = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-123"},
    ).json()["data"]
    return data["access_token"], data["user"]["id"]


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_deepseek_key_reference_is_fixed_and_secret_is_redacted(
    client: TestClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "deepseek_api_key", SecretStr("deepseek-secret-value"))
    admin_token, admin_id = register(client, "key-semantics-admin@example.com")
    async with session_factory() as session:
        admin = await session.get(User, admin_id)
        admin.role = "admin"
        await session.commit()
    auth = headers(admin_token)
    base = {
        "capability": "text",
        "provider": "deepseek",
        "model_name": "deepseek-v4-flash",
        "prompt_version": "v1",
        "min_rounds": 6,
        "max_rounds": 12,
        "enabled": True,
    }

    created = client.put(
        "/api/v1/admin/ai-settings",
        headers=auth,
        json=base,
    )
    preserved = client.put(
        "/api/v1/admin/ai-settings",
        headers=auth,
        json=base | {"model_name": "deepseek-v4-pro"},
    )
    async with session_factory() as session:
        text_config = await session.scalar(
            select(AIModelConfig).where(AIModelConfig.capability == "text")
        )
        preserved_ref = text_config.api_key_ref

    omitted_on_create = client.put(
        "/api/v1/admin/ai-settings",
        headers=auth,
        json={
            "capability": "stt",
            "provider": "browser",
            "model_name": "web-speech-recognition",
        },
    )
    async with session_factory() as session:
        stt_config = await session.scalar(
            select(AIModelConfig).where(AIModelConfig.capability == "stt")
        )
        new_omitted_ref = stt_config.api_key_ref

    assert created.json()["data"]["api_key_configured"] is True
    assert preserved.json()["data"]["api_key_configured"] is True
    assert preserved_ref == "DEEPSEEK_API_KEY"
    assert omitted_on_create.status_code == 200
    assert new_omitted_ref is None
    for response in (created, preserved, omitted_on_create):
        payload = response.text
        assert "api_key_ref" not in payload
        assert "DEEPSEEK_API_KEY" not in payload
        assert "deepseek-secret-value" not in payload


@pytest.mark.asyncio
async def test_admin_settings_require_admin_and_redact_keys(
    client: TestClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user_token, _ = register(client, "user@example.com")
    denied = client.get("/api/v1/admin/ai-settings", headers=headers(user_token))
    assert denied.status_code == 403

    admin_token, admin_id = register(client, "admin@example.com")
    async with session_factory() as session:
        admin = await session.get(User, admin_id)
        admin.role = "admin"
        await session.commit()

    initial = client.get("/api/v1/admin/ai-settings", headers=headers(admin_token))
    assert initial.status_code == 200
    assert {item["capability"] for item in initial.json()["data"]} == {"text", "stt", "tts"}
    text_setting = next(item for item in initial.json()["data"] if item["capability"] == "text")
    assert text_setting["base_url"] == "https://api.deepseek.com"

    plaintext_key = client.put(
        "/api/v1/admin/ai-settings",
        headers=headers(admin_token),
        json={
            "capability": "text",
            "provider": "mock",
            "model_name": "mock",
            "api_key": "must-not-be-accepted",
        },
    )
    assert plaintext_key.status_code == 422

    updated = client.put(
        "/api/v1/admin/ai-settings",
        headers=headers(admin_token),
        json={
            "capability": "text",
            "provider": "mock",
            "model_name": "mock-structured-v2",
            "api_key_ref": "FINANCE_GOD_TEXT_API_KEY",
            "prompt_version": "v2",
            "prompt_content": "Version two onboarding policy",
            "min_rounds": 7,
            "max_rounds": 10,
            "enabled": True,
        },
    )
    assert updated.status_code == 200
    config = updated.json()["data"]
    assert config["version"] == 1
    assert config["api_key_configured"] is False
    assert "api_key" not in config
    assert "api_key_ref" not in config

    async with session_factory() as session:
        audit = await session.scalar(
            select(AdminAuditRecord).where(
                AdminAuditRecord.actor_id == admin_id,
                AdminAuditRecord.action == "ai_settings.update",
            )
        )
        assert audit is not None
        assert audit.action == "ai_settings.update"
        assert audit.after_data["version"] == 1
        assert "api_key_ref" not in audit.after_data
        prompt = await session.scalar(
            select(PromptVersion).where(PromptVersion.version == "v2")
        )
        assert prompt is not None
        assert prompt.content == "Version two onboarding policy"


@pytest.mark.asyncio
async def test_admin_settings_validate_rounds_and_connection_test(
    client: TestClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    admin_token, admin_id = register(client, "admin2@example.com")
    async with session_factory() as session:
        admin = await session.get(User, admin_id)
        admin.role = "admin"
        await session.commit()

    invalid = client.put(
        "/api/v1/admin/ai-settings",
        headers=headers(admin_token),
        json={
            "capability": "text",
            "provider": "mock",
            "model_name": "mock",
            "min_rounds": 11,
            "max_rounds": 7,
            "enabled": True,
        },
    )
    assert invalid.status_code == 422

    unsupported = client.put(
        "/api/v1/admin/ai-settings",
        headers=headers(admin_token),
        json={
            "capability": "text",
            "provider": "unknown-cloud",
            "model_name": "unknown",
            "prompt_version": "v1",
            "min_rounds": 6,
            "max_rounds": 12,
            "enabled": True,
        },
    )
    assert unsupported.status_code == 422

    tested = client.post(
        "/api/v1/admin/ai-settings/test",
        headers=headers(admin_token),
        json={"capability": "text", "provider": "mock", "model_name": "mock"},
    )
    assert tested.status_code == 200
    assert tested.json()["data"]["ok"] is True

    configured = client.put(
        "/api/v1/admin/ai-settings",
        headers=headers(admin_token),
        json={
            "capability": "text",
            "provider": "mock",
            "model_name": "configured-mock",
            "prompt_version": "v3",
            "prompt_content": "Configured version three onboarding prompt.",
            "min_rounds": 7,
            "max_rounds": 10,
            "enabled": True,
        },
    )
    assert configured.status_code == 200

    user_token, _ = register(client, "configured-user@example.com")
    created = client.post(
        "/api/v1/onboarding/sessions", headers=headers(user_token)
    )
    session = created.json()["data"]
    assert session["model_name"] == "configured-mock"
    assert session["prompt_version"] == "v3"
    assert session["min_rounds"] == 7
    assert session["max_rounds"] == 10


@pytest.mark.asyncio
async def test_prompt_versions_are_immutable_and_separately_audited(
    client: TestClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    admin_token, admin_id = register(client, "prompt-admin@example.com")
    async with session_factory() as session:
        admin = await session.get(User, admin_id)
        admin.role = "admin"
        await session.commit()
    payload = {
        "capability": "text",
        "provider": "mock",
        "model_name": "mock",
        "prompt_version": "immutable-v1",
        "prompt_content": "Original immutable prompt content for onboarding.",
        "min_rounds": 6,
        "max_rounds": 12,
        "enabled": True,
    }

    created = client.put("/api/v1/admin/ai-settings", headers=headers(admin_token), json=payload)
    user_token, _ = register(client, "prompt-pinned-user@example.com")
    pinned = client.post(
        "/api/v1/onboarding/sessions", headers=headers(user_token)
    ).json()["data"]
    changed = client.put(
        "/api/v1/admin/ai-settings",
        headers=headers(admin_token),
        json=payload | {"prompt_content": "Changed content must not replace this prompt version."},
    )

    assert created.status_code == 200
    assert changed.status_code == 409
    next_version = client.put(
        "/api/v1/admin/ai-settings",
        headers=headers(admin_token),
        json=payload
        | {
            "prompt_version": "immutable-v2",
            "prompt_content": "A separate immutable second prompt version.",
        },
    )
    assert next_version.status_code == 200
    resumed = client.get(
        "/api/v1/onboarding/sessions/current", headers=headers(user_token)
    ).json()["data"]
    assert resumed["id"] == pinned["id"]
    assert resumed["prompt_version"] == "immutable-v1"
    async with session_factory() as session:
        prompt = await session.scalar(select(PromptVersion).where(PromptVersion.version == "immutable-v1"))
        assert prompt.content == payload["prompt_content"]
        audits = (
            await session.scalars(
                select(AdminAuditRecord).where(
                    AdminAuditRecord.actor_id == admin_id,
                    AdminAuditRecord.action == "prompt_version.create",
                )
            )
        ).all()
        first_audit = next(
            audit for audit in audits if audit.after_data["version"] == "immutable-v1"
        )
        assert first_audit.before_data == {}
        assert first_audit.after_data == {"version": "immutable-v1", "active": True}
