from fastapi.testclient import TestClient


def test_ai_evidence_is_pending_until_explicitly_confirmed(client: TestClient) -> None:
    registration = client.post(
        "/api/v1/auth/register",
        json={"email": "confirmation@example.com", "password": "correct-horse-123"},
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
            "investment_experience": "intermediate",
            "fund_horizon": "5_plus_years",
            "loss_reaction": "hold",
        },
    )

    first = client.post(
        f"/api/v1/onboarding/sessions/{session['id']}/messages",
        headers=headers,
        json={"content": "I can accept long term volatility", "input_mode": "text"},
    )
    assert first.status_code == 200
    state = first.json()["data"]["session"]
    assert state["profile_evidence"] == {}
    assert state["pending_profile_evidence"] == {
        "dimension": "risk_tolerance",
        "value": 0.8,
        "confidence": 0.72,
        "proposed_followup_count": 1,
        "proposed_round_count": 1,
        "should_continue": True,
        "end_reason": None,
        "next_question": state["pending_profile_evidence"]["next_question"],
        "next_question_dimension": "liquidity_need",
        "retry_question": state["pending_profile_evidence"]["retry_question"],
    }
    assert state["dimension_scores"] == {}
    assert state["followup_counts"] == {}
    assert state["round_count"] == 0
    assert state["completeness"] == 0.4
    assert state["current_dimension"] == "risk_tolerance"
    initial_question = state["current_question"]
    assert state["pending_profile_evidence"]["next_question_dimension"] == "liquidity_need"
    assert "I can accept long term" in state["pending_profile_evidence"]["next_question"]
    assert state["pending_profile_evidence"]["retry_question"] != initial_question

    blocked = client.post(
        f"/api/v1/onboarding/sessions/{session['id']}/messages",
        headers=headers,
        json={"content": "My next answer", "input_mode": "text"},
    )
    assert blocked.status_code == 409

    confirmed = client.post(
        f"/api/v1/onboarding/sessions/{session['id']}/messages",
        headers=headers,
        json={
            "request_id": "20000000-0000-4000-8000-000000000001",
            "confirm_pending": True,
        },
    )
    assert confirmed.status_code == 200
    confirmed_state = confirmed.json()["data"]["session"]
    assert confirmed_state["profile_evidence"] == {"risk_tolerance": 0.8}
    assert confirmed_state["pending_profile_evidence"] is None
    assert confirmed_state["current_dimension"] == "liquidity_need"
    assert confirmed_state["current_question"] == state["pending_profile_evidence"]["next_question"]
    assert confirmed.json()["data"]["accepted"] is True
    replayed = client.post(
        f"/api/v1/onboarding/sessions/{session['id']}/messages",
        headers=headers,
        json={
            "request_id": "20000000-0000-4000-8000-000000000001",
            "confirm_pending": True,
        },
    )
    assert replayed.json()["data"] == confirmed.json()["data"]


def test_pending_evidence_can_be_rejected_without_affecting_confirmed_state(client: TestClient) -> None:
    registration = client.post(
        "/api/v1/auth/register",
        json={"email": "reject-evidence@example.com", "password": "correct-horse-123"},
    ).json()["data"]
    headers = {"Authorization": f"Bearer {registration['access_token']}"}
    session = client.post("/api/v1/onboarding/sessions", headers=headers).json()["data"]
    objective = {
        "gender": "prefer_not_to_say", "age_range": "36-45", "asset_level": "A5",
        "employment_status": "employed", "income_range": "I5", "debt_pressure": "low",
        "emergency_fund_months": 6, "investment_experience": "intermediate",
        "fund_horizon": "5_plus_years", "loss_reaction": "hold",
    }
    client.put(f"/api/v1/onboarding/sessions/{session['id']}/objective-profile", headers=headers, json=objective)
    client.post(
        f"/api/v1/onboarding/sessions/{session['id']}/messages",
        headers=headers,
        json={"content": "I can accept volatility", "input_mode": "text"},
    )

    pending_state = client.get(
        "/api/v1/onboarding/sessions/current", headers=headers
    ).json()["data"]

    rejected = client.post(
        f"/api/v1/onboarding/sessions/{session['id']}/messages",
        headers=headers,
        json={
            "request_id": "20000000-0000-4000-8000-000000000002",
            "confirm_pending": False,
        },
    )

    assert rejected.status_code == 200
    assert rejected.json()["data"]["accepted"] is False
    assert rejected.json()["data"]["session"]["profile_evidence"] == {}
    assert rejected.json()["data"]["session"]["pending_profile_evidence"] is None
    assert rejected.json()["data"]["session"]["dimension_scores"] == {}
    assert rejected.json()["data"]["session"]["followup_counts"] == {}
    assert rejected.json()["data"]["session"]["round_count"] == 0
    assert rejected.json()["data"]["session"]["turn_count"] == 1
    assert rejected.json()["data"]["session"]["completeness"] == 0.4
    assert rejected.json()["data"]["session"]["current_dimension"] == "risk_tolerance"
    assert rejected.json()["data"]["session"]["current_question"] == pending_state["pending_profile_evidence"]["retry_question"]
    assert rejected.json()["data"]["session"]["current_question"] != pending_state["current_question"]
    refreshed = client.get(
        "/api/v1/onboarding/sessions/current", headers=headers
    ).json()["data"]
    assert refreshed["current_question"] == rejected.json()["data"]["session"]["current_question"]
