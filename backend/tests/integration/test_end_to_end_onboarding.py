"""P2 集成测试：从注册到方向选择的端到端引导旅程。

沿用既有集成测试风格：默认 AI 注册表即内置 mock 编排器
（与 tests/integration/test_onboarding_api.py 一致，无需真实调用外部模型）。
"""

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.onboarding import OnboardingSession


PASSWORD = "correct-horse-123"


def adult_profile() -> dict:
    return {
        "gender": "prefer_not_to_say",
        "age_range": "36-45",
        "asset_level": "A6",
        "employment_status": "employed",
        "income_range": "I5",
        "debt_pressure": "low",
        "emergency_fund_months": 8,
        "investment_experience": "intermediate",
        "fund_horizon": "5_plus_years",
        "loss_reaction": "hold",
    }


def register_and_login(client: TestClient, email: str) -> dict[str, str]:
    registered = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "display_name": "旅程用户"},
    )
    assert registered.status_code == 201

    logged_in = client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert logged_in.status_code == 200
    token = logged_in.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def start_conversation(client: TestClient, headers: dict[str, str]) -> str:
    created = client.post("/api/v1/onboarding/sessions", headers=headers)
    assert created.status_code == 201
    session = created.json()["data"]
    assert session["step"] == "objective_profile"

    updated = client.put(
        f"/api/v1/onboarding/sessions/{session['id']}/objective-profile",
        headers=headers,
        json=adult_profile(),
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["step"] == "conversation"
    return session["id"]


def test_full_onboarding_journey_from_register_to_direction_selection(
    client: TestClient,
) -> None:
    headers = register_and_login(client, "journey@example.com")
    session_id = start_conversation(client, headers)

    # 多轮对话（默认 mock 编排器），前 5 轮覆盖前五个维度
    for number in range(5):
        turn = client.post(
            f"/api/v1/onboarding/sessions/{session_id}/messages",
            headers=headers,
            json={
                "content": f"I can stay invested and accept volatility, answer {number}",
                "input_mode": "text",
            },
        )
        assert turn.status_code == 200

    state = client.get("/api/v1/onboarding/sessions/current", headers=headers).json()[
        "data"
    ]
    assert state["current_dimension"] == "income_stability"

    # 跳过敏感维度（income_stability）
    skipped = client.post(
        f"/api/v1/onboarding/sessions/{session_id}/skip",
        headers=headers,
        json={"dimension": "income_stability"},
    )
    assert skipped.status_code == 200
    assert "income_stability" in skipped.json()["data"]["skipped_dimensions"]
    assert skipped.json()["data"]["status"] == "ready"

    # 完成画像
    completed = client.post(
        f"/api/v1/onboarding/sessions/{session_id}/complete", headers=headers
    )
    assert completed.status_code == 200
    completed_data = completed.json()["data"]
    profile_id = completed_data["profile"]["id"]
    recommendations = completed_data["recommendations"]
    assert len(recommendations) == 5
    assert [item["rank"] for item in recommendations] == [1, 2, 3, 4, 5]

    # 最新画像
    latest = client.get("/api/v1/profiles/me/latest", headers=headers)
    assert latest.status_code == 200
    assert latest.json()["data"]["profile"]["id"] == profile_id

    # 方向选择
    direction = recommendations[0]["direction"]
    selected = client.post(
        f"/api/v1/profiles/{profile_id}/direction-selection",
        headers=headers,
        json={"selected_direction": direction},
    )
    assert selected.status_code == 200
    assert selected.json()["data"]["selected_direction"] == direction
    assert selected.json()["data"]["selected"] is True


def test_duplicate_request_id_message_does_not_consume_extra_round(
    client: TestClient,
) -> None:
    headers = register_and_login(client, "journey-idempotent@example.com")
    session_id = start_conversation(client, headers)
    payload = {
        "request_id": "1e58a3c0-93a1-4a5c-9a54-1f6a5f7b0c11",
        "content": "I can accept long term volatility",
        "input_mode": "text",
    }

    first = client.post(
        f"/api/v1/onboarding/sessions/{session_id}/messages",
        headers=headers,
        json=payload,
    )
    duplicate = client.post(
        f"/api/v1/onboarding/sessions/{session_id}/messages",
        headers=headers,
        json=payload,
    )

    assert first.status_code == 200
    assert duplicate.status_code == 200
    # 重放返回同一条 assistant 消息，不重复计轮
    assert (
        duplicate.json()["data"]["assistant_message"]["id"]
        == first.json()["data"]["assistant_message"]["id"]
    )
    state = client.get("/api/v1/onboarding/sessions/current", headers=headers).json()[
        "data"
    ]
    assert state["round_count"] == 1
    assert state["turn_count"] == 1


async def test_max_rounds_forces_completion_path(
    client: TestClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    headers = register_and_login(client, "journey-max-rounds@example.com")
    session_id = start_conversation(client, headers)

    # 将会话推进到最大提供方调用上限（12）前一轮
    async with session_factory() as db:
        onboarding = await db.get(OnboardingSession, session_id)
        assert onboarding is not None
        onboarding.turn_count = 11
        await db.commit()

    final_turn = client.post(
        f"/api/v1/onboarding/sessions/{session_id}/messages",
        headers=headers,
        json={"content": "A final answer at the round limit", "input_mode": "text"},
    )
    assert final_turn.status_code == 200
    final_state = final_turn.json()["data"]["session"]
    assert final_state["turn_count"] == 12
    assert final_state["status"] == "ready"
    assert final_state["current_question"] is None

    # 上限后的消息被拒绝，会话只能走完成路径
    rejected = client.post(
        f"/api/v1/onboarding/sessions/{session_id}/messages",
        headers=headers,
        json={"content": "One more answer past the cap", "input_mode": "text"},
    )
    assert rejected.status_code == 409

    completed = client.post(
        f"/api/v1/onboarding/sessions/{session_id}/complete", headers=headers
    )
    assert completed.status_code == 200
    assert len(completed.json()["data"]["recommendations"]) == 5
