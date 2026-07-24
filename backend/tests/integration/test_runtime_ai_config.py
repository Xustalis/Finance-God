import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.main import app
from app.config import settings
from app.models.ai_config import AIModelConfig, PromptVersion
from app.models.user import User
from app.services.ai_orchestrator import AIAdapterRegistry, MockTextProvider, ONBOARDING_SYSTEM_PROMPT, get_ai_adapter_registry


class CapturingRegistry(AIAdapterRegistry):
    def __init__(self) -> None:
        super().__init__()
        self.resolved: dict | None = None

    def resolve_text(self, **kwargs):
        self.resolved = kwargs
        return super().resolve_text(**kwargs)


class ProductionRegistry(AIAdapterRegistry):
    def __init__(self) -> None:
        super().__init__()
        self.text_providers["cloud"] = MockTextProvider()


@pytest.mark.asyncio
async def test_production_session_requires_enabled_supported_non_mock_provider(
    client: TestClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "app_env", "production")
    first = client.post(
        "/api/v1/auth/register",
        json={"email": "production-no-config@example.com", "password": "correct-horse-123"},
    ).json()["data"]
    no_config = client.post(
        "/api/v1/onboarding/sessions",
        headers={"Authorization": f"Bearer {first['access_token']}"},
    )

    async with session_factory() as db:
        config = AIModelConfig(
            capability="text",
            provider="mock",
            model_name="mock",
            prompt_version="v1",
            enabled=True,
        )
        db.add(config)
        await db.commit()
    second = client.post(
        "/api/v1/auth/register",
        json={"email": "production-mock@example.com", "password": "correct-horse-123"},
    ).json()["data"]
    mock_config = client.post(
        "/api/v1/onboarding/sessions",
        headers={"Authorization": f"Bearer {second['access_token']}"},
    )

    async with session_factory() as db:
        config = await db.get(AIModelConfig, config.id)
        config.provider = "cloud"
        config.model_name = "cloud-model"
        await db.commit()
    registry = ProductionRegistry()
    app.dependency_overrides[get_ai_adapter_registry] = lambda: registry
    third = client.post(
        "/api/v1/auth/register",
        json={"email": "production-cloud@example.com", "password": "correct-horse-123"},
    ).json()["data"]
    supported = client.post(
        "/api/v1/onboarding/sessions",
        headers={"Authorization": f"Bearer {third['access_token']}"},
    )

    assert no_config.status_code == 503
    assert mock_config.status_code == 503
    assert supported.status_code == 201
    assert supported.json()["data"]["provider_name"] == "cloud"


@pytest.mark.asyncio
async def test_active_provider_model_and_prompt_configure_runtime_orchestrator(
    client: TestClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    admin_registration = client.post(
        "/api/v1/auth/register",
        json={"email": "runtime-admin@example.com", "password": "correct-horse-123"},
    ).json()["data"]
    async with session_factory() as session:
        admin = await session.get(User, admin_registration["user"]["id"])
        admin.role = "admin"
        await session.commit()
    admin_headers = {"Authorization": f"Bearer {admin_registration['access_token']}"}
    configured = client.put(
        "/api/v1/admin/ai-settings",
        headers=admin_headers,
        json={
            "capability": "text",
            "provider": "mock",
            "model_name": "configured-model",
            "prompt_version": "runtime-v1",
            "prompt_content": "Runtime prompt content that must reach the selected orchestrator.",
            "min_rounds": 6,
            "max_rounds": 12,
            "enabled": True,
        },
    )
    assert configured.status_code == 200

    user_registration = client.post(
        "/api/v1/auth/register",
        json={"email": "runtime-user@example.com", "password": "correct-horse-123"},
    ).json()["data"]
    user_headers = {"Authorization": f"Bearer {user_registration['access_token']}"}
    onboarding = client.post("/api/v1/onboarding/sessions", headers=user_headers).json()["data"]
    client.put(
        f"/api/v1/onboarding/sessions/{onboarding['id']}/objective-profile",
        headers=user_headers,
        json={
            "gender": "prefer_not_to_say",
            "age_range": "36-45",
            "asset_level": "A5",
            "employment_status": "employed",
            "income_range": "I5",
            "debt_pressure": "low",
            "emergency_fund_months": 6,
            "investment_experience": "intermediate",
            "fund_horizon": "5_plus_years",
            "loss_reaction": "hold",
        },
    )
    registry = CapturingRegistry()
    app.dependency_overrides[get_ai_adapter_registry] = lambda: registry
    response = client.post(
        f"/api/v1/onboarding/sessions/{onboarding['id']}/messages",
        headers=user_headers,
        json={"content": "I can accept long term volatility", "input_mode": "text"},
    )

    assert response.status_code == 200
    assert registry.resolved == {
        "provider": "mock",
        "model_name": "configured-model",
        "system_prompt": "Runtime prompt content that must reach the selected orchestrator.",
    }


@pytest.mark.asyncio
async def test_session_prompt_is_pinned_before_late_prompt_row_creation(
    client: TestClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    registration = client.post(
        "/api/v1/auth/register",
        json={"email": "pinned-default@example.com", "password": "correct-horse-123"},
    ).json()["data"]
    headers = {"Authorization": f"Bearer {registration['access_token']}"}
    onboarding = client.post("/api/v1/onboarding/sessions", headers=headers).json()["data"]
    original_hash = onboarding["prompt_hash"]
    assert original_hash

    async with session_factory() as session:
        session.add(
            PromptVersion(
                version="v1",
                content="Late content that must not affect an existing session.",
                active=True,
            )
        )
        await session.commit()

    client.put(
        f"/api/v1/onboarding/sessions/{onboarding['id']}/objective-profile",
        headers=headers,
        json={
            "gender": "prefer_not_to_say", "age_range": "36-45", "asset_level": "A5",
            "employment_status": "employed", "income_range": "I5", "debt_pressure": "low",
            "emergency_fund_months": 6, "investment_experience": "intermediate",
            "fund_horizon": "5_plus_years", "loss_reaction": "hold",
        },
    )
    registry = CapturingRegistry()
    app.dependency_overrides[get_ai_adapter_registry] = lambda: registry
    response = client.post(
        f"/api/v1/onboarding/sessions/{onboarding['id']}/messages",
        headers=headers,
        json={"content": "A detailed answer", "input_mode": "text"},
    )

    assert response.status_code == 200
    assert registry.resolved["system_prompt"] == ONBOARDING_SYSTEM_PROMPT
    assert response.json()["data"]["session"]["prompt_hash"] == original_hash
