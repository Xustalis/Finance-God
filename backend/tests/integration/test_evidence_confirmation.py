from fastapi.testclient import TestClient


def start_conversation(client: TestClient, email: str) -> tuple[dict[str, str], str]:
    registration = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-123"},
    ).json()["data"]
    headers = {"Authorization": f"Bearer {registration['access_token']}"}
    session = client.post("/api/v1/onboarding/sessions", headers=headers).json()["data"]
    client.put(
        f"/api/v1/onboarding/sessions/{session['id']}/objective-profile",
        headers=headers,
        json={
            "gender": "prefer_not_to_say",
            "age_range": "36-45",
            "asset_level": "A5",
            "employment_status": "employed",
            "income_range": "I5",
            "debt_pressure": "low",
            "emergency_fund_months": 6,
            "investment_experience": "beginner",
            "fund_horizon": "5_plus_years",
            "loss_reaction": "hold",
        },
    )
    return headers, session["id"]


def test_answer_automatically_updates_profile_and_advances_question(client: TestClient) -> None:
    headers, session_id = start_conversation(client, "automatic-profile@example.com")

    response = client.post(
        f"/api/v1/onboarding/sessions/{session_id}/messages",
        headers=headers,
        json={
            "request_id": "20000000-0000-4000-8000-000000000001",
            "content": "I can accept long term volatility",
            "input_mode": "text",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    state = data["session"]
    assert state["profile_evidence"] == {"risk_tolerance": 0.8}
    assert state["dimension_scores"] == {"risk_tolerance": 0.72}
    assert state["followup_counts"] == {"risk_tolerance": 1}
    assert state["round_count"] == 1
    assert state["turn_count"] == 1
    assert state["completeness"] == 0.5
    assert state["current_dimension"] == "liquidity_need"
    assert "I can accept long term" in state["current_question"]
    assert "pending_profile_evidence" not in state
    assert data["assistant_message"]["content"]


def test_confirmation_command_is_no_longer_part_of_message_contract(client: TestClient) -> None:
    headers, session_id = start_conversation(client, "retired-confirmation@example.com")

    response = client.post(
        f"/api/v1/onboarding/sessions/{session_id}/messages",
        headers=headers,
        json={
            "request_id": "20000000-0000-4000-8000-000000000002",
            "confirm_pending": True,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
