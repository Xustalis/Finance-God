from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.main import app
from app.models.onboarding import OnboardingSession, ProfileMessage
from app.services.ai_orchestrator import AIAdapterRegistry, get_ai_adapter_registry
from app.models.profile import DirectionRecommendation, InvestmentProfile


class CountingRegistry(AIAdapterRegistry):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def resolve_text(self, **kwargs):
        orchestrator = super().resolve_text(**kwargs)
        original = orchestrator.respond

        async def counted(**turn_kwargs):
            self.calls += 1
            return await original(**turn_kwargs)

        orchestrator.respond = counted
        return orchestrator


def start_conversation(client: TestClient, email: str) -> tuple[dict[str, str], dict]:
    registered = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-123"},
    ).json()["data"]
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    session = client.post("/api/v1/onboarding/sessions", headers=headers).json()["data"]
    objective = {
        "gender": "prefer_not_to_say", "age_range": "36-45", "asset_level": "A5",
        "employment_status": "employed", "income_range": "I5", "debt_pressure": "low",
        "emergency_fund_months": 6, "investment_experience": "intermediate",
        "fund_horizon": "5_plus_years", "loss_reaction": "hold",
    }
    client.put(f"/api/v1/onboarding/sessions/{session['id']}/objective-profile", headers=headers, json=objective)
    return headers, session


def test_duplicate_message_request_id_returns_same_result_without_provider_replay(client: TestClient) -> None:
    headers, session = start_conversation(client, "idempotent-message@example.com")
    registry = CountingRegistry()
    app.dependency_overrides[get_ai_adapter_registry] = lambda: registry
    payload = {
        "request_id": "9fb52ee2-3e30-43ca-98c2-28df975fbf0e",
        "content": "I can accept long term volatility",
        "input_mode": "text",
    }

    first = client.post(f"/api/v1/onboarding/sessions/{session['id']}/messages", headers=headers, json=payload)
    duplicate = client.post(f"/api/v1/onboarding/sessions/{session['id']}/messages", headers=headers, json=payload)

    assert first.status_code == 200
    assert duplicate.status_code == 200
    assert registry.calls == 1
    assert duplicate.json()["data"]["assistant_message"]["id"] == first.json()["data"]["assistant_message"]["id"]


@pytest.mark.asyncio
async def test_different_request_id_is_blocked_by_active_claim_before_provider(
    client: TestClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    headers, session = start_conversation(client, "active-claim@example.com")
    async with session_factory() as db:
        onboarding = await db.get(OnboardingSession, session["id"])
        onboarding.turn_count = 1
        db.add(
            ProfileMessage(
                session_id=session["id"],
                request_id="7a796fc8-5142-4b80-a407-c84f3ddda190",
                role="user",
                content="Still processing",
                input_mode="text",
            )
        )
        await db.commit()
    registry = CountingRegistry()
    app.dependency_overrides[get_ai_adapter_registry] = lambda: registry

    response = client.post(
        f"/api/v1/onboarding/sessions/{session['id']}/messages",
        headers=headers,
        json={
            "request_id": "59f8d8fe-acde-4c0a-bd0c-3a888039a8c1",
            "content": "A different request",
        },
    )

    assert response.status_code == 409
    assert registry.calls == 0


@pytest.mark.asyncio
async def test_expired_claim_is_recovered_before_new_provider_call(
    client: TestClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    headers, session = start_conversation(client, "expired-claim@example.com")
    async with session_factory() as db:
        onboarding = await db.get(OnboardingSession, session["id"])
        onboarding.turn_count = 1
        db.add(
            ProfileMessage(
                session_id=session["id"],
                request_id="7d136b0e-f483-4af3-8574-14d251c2c75e",
                role="user",
                content="Abandoned request",
                input_mode="text",
                created_at=datetime.now(timezone.utc) - timedelta(minutes=10),
            )
        )
        await db.commit()
    registry = CountingRegistry()
    app.dependency_overrides[get_ai_adapter_registry] = lambda: registry

    response = client.post(
        f"/api/v1/onboarding/sessions/{session['id']}/messages",
        headers=headers,
        json={
            "request_id": "5d358f5e-39dc-4e15-b498-552916552db3",
            "content": "Retry after abandoned work",
        },
    )

    assert response.status_code == 200
    assert registry.calls == 1
    assert response.json()["data"]["session"]["turn_count"] == 1


def test_profile_version_is_unique_per_user() -> None:
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in InvestmentProfile.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }

    assert ("user_id", "version") in unique_columns


def test_direction_and_rank_are_unique_per_profile() -> None:
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in DirectionRecommendation.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }

    assert ("profile_id", "direction") in unique_columns
    assert ("profile_id", "rank") in unique_columns
