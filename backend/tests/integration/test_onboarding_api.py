import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.ai_config import AIModelConfig


def register(client: TestClient, email: str) -> tuple[str, dict]:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-123"},
    )
    data = response.json()["data"]
    return data["access_token"], data["user"]


def authorization(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


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


async def configure_text_rounds(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    min_rounds: int,
    max_rounds: int = 12,
) -> None:
    async with session_factory() as db:
        db.add(
            AIModelConfig(
                capability="text",
                provider="mock",
                model_name="mock-structured-v1",
                prompt_version="v1",
                min_rounds=min_rounds,
                max_rounds=max_rounds,
                enabled=True,
            )
        )
        await db.commit()


def test_session_is_resumable_and_objective_profile_advances_step(client: TestClient) -> None:
    token, _ = register(client, "resume@example.com")
    headers = authorization(token)

    created = client.post("/api/v1/onboarding/sessions", headers=headers)

    assert created.status_code == 201
    session = created.json()["data"]
    assert session["step"] == "objective_profile"
    assert session["status"] == "active"

    resumed = client.get("/api/v1/onboarding/sessions/current", headers=headers)
    assert resumed.status_code == 200
    assert resumed.json()["data"]["id"] == session["id"]

    updated = client.put(
        f"/api/v1/onboarding/sessions/{session['id']}/objective-profile",
        headers=headers,
        json=adult_profile(),
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["step"] == "conversation"
    assert updated.json()["data"]["objective_profile"]["asset_level"] == "A6"
    initial_question = updated.json()["data"]["current_question"]
    assert "阶段性亏损" in initial_question
    assert "收益" not in initial_question
    refreshed = client.get("/api/v1/onboarding/sessions/current", headers=headers)
    assert refreshed.json()["data"]["current_question"] == initial_question
    rewritten = client.put(
        f"/api/v1/onboarding/sessions/{session['id']}/objective-profile",
        headers=headers,
        json=adult_profile() | {"asset_level": "A9"},
    )
    assert rewritten.status_code == 409


def test_user_cannot_update_another_users_session(client: TestClient) -> None:
    owner_token, _ = register(client, "owner@example.com")
    other_token, _ = register(client, "other@example.com")
    session_id = client.post(
        "/api/v1/onboarding/sessions", headers=authorization(owner_token)
    ).json()["data"]["id"]

    response = client.put(
        f"/api/v1/onboarding/sessions/{session_id}/objective-profile",
        headers=authorization(other_token),
        json=adult_profile(),
    )

    assert response.status_code == 404


def test_sensitive_skip_is_neutral_and_followups_are_bounded(client: TestClient) -> None:
    token, _ = register(client, "skip@example.com")
    headers = authorization(token)
    session = client.post("/api/v1/onboarding/sessions", headers=headers).json()["data"]
    client.put(
        f"/api/v1/onboarding/sessions/{session['id']}/objective-profile",
        headers=headers,
        json=adult_profile(),
    )
    targets = []
    for number in range(5):
        turn = client.post(
            f"/api/v1/onboarding/sessions/{session['id']}/messages",
            headers=headers,
            json={
                "content": f"This is a neutral answer {number}",
                "input_mode": "text",
            },
        )
        assert turn.status_code == 200
        turn_data = turn.json()["data"]
        assert set(turn_data["turn"]) >= {
            "reply",
            "target_dimension",
            "sensitive",
            "profile_delta",
            "confidence",
            "should_continue",
            "end_reason",
        }
        targets.append(turn_data["turn"]["target_dimension"])

    before = client.get("/api/v1/onboarding/sessions/current", headers=headers).json()["data"]
    assert before["current_dimension"] == "income_stability"
    assert before["current_question"]

    skipped = client.post(
        f"/api/v1/onboarding/sessions/{session['id']}/skip",
        headers=headers,
        json={"dimension": "income_stability"},
    )

    assert skipped.status_code == 200
    assert "income_stability" in skipped.json()["data"]["skipped_dimensions"]
    assert skipped.json()["data"]["completeness"] >= before["completeness"]
    assert "income_stability" not in skipped.json()["data"]["dimension_scores"]
    assert skipped.json()["data"]["round_count"] == 6
    assert skipped.json()["data"]["status"] == "ready"
    assert skipped.json()["data"]["current_question"] is None

    assert all(targets.count(target) <= 2 for target in set(targets))


@pytest.mark.asyncio
async def test_minimum_eight_rounds_adds_bounded_followups_after_six_dimensions(
    client: TestClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await configure_text_rounds(session_factory, min_rounds=8)
    token, _ = register(client, "minimum-eight@example.com")
    headers = authorization(token)
    session = client.post("/api/v1/onboarding/sessions", headers=headers).json()["data"]
    client.put(
        f"/api/v1/onboarding/sessions/{session['id']}/objective-profile",
        headers=headers,
        json=adult_profile(),
    )

    targets = []
    turn = None
    for number in range(8):
        turn = client.post(
            f"/api/v1/onboarding/sessions/{session['id']}/messages",
            headers=headers,
            json={"content": f"I can accept long term volatility, answer {number}"},
        )
        assert turn.status_code == 200
        targets.append(turn.json()["data"]["turn"]["target_dimension"])

    assert turn is not None
    state = turn.json()["data"]["session"]
    assert state["status"] == "ready"
    assert state["round_count"] == 8
    assert state["current_question"] is None
    assert targets[:6] == [
        "risk_tolerance",
        "liquidity_need",
        "investment_goal",
        "loss_behavior",
        "investment_knowledge",
        "income_stability",
    ]
    assert targets[6:] == ["risk_tolerance", "liquidity_need"]
    assert all(targets.count(target) <= 2 for target in set(targets))


@pytest.mark.asyncio
async def test_minimum_eight_rounds_skip_last_sensitive_dimension_uses_followup(
    client: TestClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await configure_text_rounds(session_factory, min_rounds=8)
    token, _ = register(client, "minimum-eight-skip@example.com")
    headers = authorization(token)
    session = client.post("/api/v1/onboarding/sessions", headers=headers).json()["data"]
    client.put(
        f"/api/v1/onboarding/sessions/{session['id']}/objective-profile",
        headers=headers,
        json=adult_profile(),
    )
    turn = None
    for number in range(5):
        turn = client.post(
            f"/api/v1/onboarding/sessions/{session['id']}/messages",
            headers=headers,
            json={"content": f"I can accept long term volatility, answer {number}"},
        )
        assert turn.status_code == 200
    assert turn is not None
    assert turn.json()["data"]["session"]["current_dimension"] == "income_stability"

    skipped = client.post(
        f"/api/v1/onboarding/sessions/{session['id']}/skip",
        headers=headers,
        json={"dimension": "income_stability"},
    )
    assert skipped.status_code == 200
    state = skipped.json()["data"]
    assert state["status"] == "active"
    assert state["round_count"] == 6
    assert state["current_dimension"] == "risk_tolerance"
    assert state["current_question"]


def _finish_profile(client: TestClient, token: str, objective: dict) -> dict:
    headers = authorization(token)
    session = client.post("/api/v1/onboarding/sessions", headers=headers).json()["data"]
    client.put(
        f"/api/v1/onboarding/sessions/{session['id']}/objective-profile",
        headers=headers,
        json=objective,
    )
    for number in range(6):
        response = client.post(
            f"/api/v1/onboarding/sessions/{session['id']}/messages",
            headers=headers,
            json={
                "content": f"I can stay invested and accept volatility, answer {number}",
                "input_mode": "text",
            },
        )
        assert response.status_code == 200
    completed = client.post(
        f"/api/v1/onboarding/sessions/{session['id']}/complete", headers=headers
    )
    assert completed.status_code == 200
    return completed.json()["data"]


def test_completion_is_deterministic_and_selection_is_persisted(client: TestClient) -> None:
    first_token, _ = register(client, "first@example.com")
    second_token, _ = register(client, "second@example.com")

    first = _finish_profile(client, first_token, adult_profile())
    second = _finish_profile(client, second_token, adult_profile())

    assert first["profile"]["archetype_code"] == second["profile"]["archetype_code"]
    assert len(first["recommendations"]) == 5
    assert [item["direction"] for item in first["recommendations"]] == [
        item["direction"] for item in second["recommendations"]
    ]
    assert [item["rank"] for item in first["recommendations"]] == [1, 2, 3, 4, 5]

    profile_id = first["profile"]["id"]
    selected_direction = first["recommendations"][0]["direction"]
    selected = client.post(
        f"/api/v1/profiles/{profile_id}/direction-selection",
        headers=authorization(first_token),
        json={"selected_direction": selected_direction},
    )
    assert selected.status_code == 200
    assert selected.json()["data"]["selected_direction"] == selected_direction

    latest = client.get(
        "/api/v1/profiles/me/latest", headers=authorization(first_token)
    )
    assert latest.status_code == 200
    assert latest.json()["data"]["profile"]["id"] == profile_id


def test_minor_profile_is_education_only(client: TestClient) -> None:
    token, _ = register(client, "minor@example.com")
    objective = adult_profile() | {"age_range": "minor"}

    completed = _finish_profile(client, token, objective)

    assert completed["profile"]["education_only"] is True
    assert completed["profile"]["archetype_title"] == "理财启蒙学习者"
    assert all(item["actionable"] is False for item in completed["recommendations"])
    assert all("金融教育" in item["reason"] for item in completed["recommendations"])
    assert all("不可执行" in item["reason"] for item in completed["recommendations"])


def test_completed_profile_exposes_style_master_match(client: TestClient) -> None:
    token, _ = register(client, "style@example.com")
    completed = _finish_profile(client, token, adult_profile())
    profile = completed["profile"]
    assert profile["style_code"] in {
        "market_growth", "value_return", "growth_discovery", "multi_asset", "trend_discipline",
    }
    assert profile["style_name"]
    assert profile["style_logic"]
    assert profile["style_summary"]
    assert profile["master_name"]
    assert profile["master_name_en"]
    assert profile["master_match_reason"]


def test_completed_session_releases_live_session_slot(client: TestClient) -> None:
    token, _ = register(client, "repeat-onboarding@example.com")
    completed = _finish_profile(client, token, adult_profile())

    next_session = client.post(
        "/api/v1/onboarding/sessions", headers=authorization(token)
    )

    assert next_session.status_code == 201
    assert next_session.json()["data"]["id"] != completed["profile"]["session_id"]


def test_server_terminates_adaptively_after_six_complete_dimensions(client: TestClient) -> None:
    token, _ = register(client, "terminal@example.com")
    headers = authorization(token)
    session = client.post("/api/v1/onboarding/sessions", headers=headers).json()["data"]
    client.put(
        f"/api/v1/onboarding/sessions/{session['id']}/objective-profile",
        headers=headers,
        json=adult_profile(),
    )

    latest = None
    for number in range(6):
        latest = client.post(
            f"/api/v1/onboarding/sessions/{session['id']}/messages",
            headers=headers,
            json={
                "content": f"A detailed confirmed answer number {number}",
                "input_mode": "text",
            },
        )
        assert latest.status_code == 200

    assert latest is not None
    assert latest.json()["data"]["session"]["status"] == "ready"
    rejected = client.post(
        f"/api/v1/onboarding/sessions/{session['id']}/messages",
        headers=headers,
        json={"content": "This turn must not be accepted", "input_mode": "text"},
    )
    assert rejected.status_code == 409
    resumed = client.post("/api/v1/onboarding/sessions", headers=headers)
    assert resumed.json()["data"]["id"] == session["id"]


def test_refusing_final_sensitive_question_completes_without_bad_gateway(client: TestClient) -> None:
    token, _ = register(client, "refuse-final@example.com")
    headers = authorization(token)
    session = client.post("/api/v1/onboarding/sessions", headers=headers).json()["data"]
    client.put(
        f"/api/v1/onboarding/sessions/{session['id']}/objective-profile",
        headers=headers,
        json=adult_profile(),
    )
    for number in range(5):
        turn = client.post(
            f"/api/v1/onboarding/sessions/{session['id']}/messages",
            headers=headers,
            json={"content": f"I can accept long term volatility, answer {number}"},
        )
        assert turn.status_code == 200
    assert turn.json()["data"]["session"]["current_dimension"] == "income_stability"

    refusal = client.post(
        f"/api/v1/onboarding/sessions/{session['id']}/messages",
        headers=headers,
        json={"content": "不想说", "input_mode": "text"},
    )

    assert refusal.status_code == 200
    state = refusal.json()["data"]["session"]
    assert state["status"] == "ready"
    assert state["current_question"] is None
    assert refusal.json()["data"]["turn"]["should_continue"] is False
    assert refusal.json()["data"]["turn"]["next_question"] is None

    completed = client.post(
        f"/api/v1/onboarding/sessions/{session['id']}/complete", headers=headers
    )
    assert completed.status_code == 200


def test_vague_answers_continue_conversation_until_completion(client: TestClient) -> None:
    token, _ = register(client, "vague-continue@example.com")
    headers = authorization(token)
    session = client.post("/api/v1/onboarding/sessions", headers=headers).json()["data"]
    client.put(
        f"/api/v1/onboarding/sessions/{session['id']}/objective-profile",
        headers=headers,
        json=adult_profile(),
    )
    for number in range(4):
        turn = client.post(
            f"/api/v1/onboarding/sessions/{session['id']}/messages",
            headers=headers,
            json={"content": f"I can accept long term volatility, answer {number}"},
        )
        assert turn.status_code == 200
    assert turn.json()["data"]["session"]["current_dimension"] == "investment_knowledge"

    first_refusal = client.post(
        f"/api/v1/onboarding/sessions/{session['id']}/messages",
        headers=headers,
        json={"content": "不想说", "input_mode": "text"},
    )
    assert first_refusal.status_code == 200
    after_first = first_refusal.json()["data"]["session"]
    assert after_first["status"] == "active"
    assert after_first["current_dimension"] == "investment_knowledge"
    assert after_first["current_question"]

    second_refusal = client.post(
        f"/api/v1/onboarding/sessions/{session['id']}/messages",
        headers=headers,
        json={"content": "不想说", "input_mode": "text"},
    )
    assert second_refusal.status_code == 200
    after_second = second_refusal.json()["data"]["session"]
    assert after_second["status"] == "ready"
    assert after_second["current_question"] is None

    completed = client.post(
        f"/api/v1/onboarding/sessions/{session['id']}/complete", headers=headers
    )
    assert completed.status_code == 200


def test_skip_requires_active_conversation_and_current_sensitive_dimension(client: TestClient) -> None:
    token, _ = register(client, "skip-boundary@example.com")
    headers = authorization(token)
    session = client.post("/api/v1/onboarding/sessions", headers=headers).json()["data"]

    before_conversation = client.post(
        f"/api/v1/onboarding/sessions/{session['id']}/skip",
        headers=headers,
        json={"dimension": "income_stability"},
    )
    assert before_conversation.status_code == 409

    client.put(
        f"/api/v1/onboarding/sessions/{session['id']}/objective-profile",
        headers=headers,
        json=adult_profile(),
    )
    not_current = client.post(
        f"/api/v1/onboarding/sessions/{session['id']}/skip",
        headers=headers,
        json={"dimension": "income_stability"},
    )
    non_sensitive = client.post(
        f"/api/v1/onboarding/sessions/{session['id']}/skip",
        headers=headers,
        json={"dimension": "risk_tolerance"},
    )
    assert not_current.status_code == 409
    assert non_sensitive.status_code == 422
    assert non_sensitive.json()["error"]["code"] == "VALIDATION_ERROR"
