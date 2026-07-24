from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
import server as finance_server
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finance_god.infrastructure.persistence.models import Base as FinanceBase


def _register(client: TestClient, email: str) -> tuple[dict[str, str], str]:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-123"},
    )
    assert response.status_code == 201
    data = response.json()["data"]
    return {"Authorization": f"Bearer {data['access_token']}"}, data["user"]["id"]


def _draft_body(account_id: str) -> dict[str, object]:
    return {
        "mode": "manual",
        "account_id": account_id,
        "instrument_id": "000001.SZ",
        "side": "buy",
        "order_type": "market",
        "quantity": 100,
        "amount": None,
        "limit_price": None,
        "time_in_force": "day",
        "fund_rule_version": None,
        "valid_until": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
        "input_versions": [
            {
                "object_type": "market_quote",
                "object_id": "000001.SZ",
                "version": "2026-07-24T08:00:00Z",
            }
        ],
        "plan_reference": None,
    }


def test_authenticated_simulation_flow_is_durable_isolated_and_atomic(
    client: TestClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_create_finance_schema(session_factory))
    monkeypatch.setattr(finance_server, "create_db_session", session_factory)
    first_headers, first_user_id = _register(client, "e2e-first@example.com")
    second_headers, _ = _register(client, "e2e-second@example.com")

    account_response = client.post(
        "/api/simulation/accounts",
        json={"initial_cash_rmb": 100000},
        headers={**first_headers, "idempotency-key": "e2e-account-first"},
    )
    assert account_response.status_code == 201
    account = account_response.json()
    assert account["owner_id"] == first_user_id

    failed_draft = client.post(
        "/api/simulation/drafts",
        json=_draft_body(account["account_id"]),
        headers={**first_headers, "idempotency-key": "e2e-draft-failed-submit"},
    )
    assert failed_draft.status_code == 201
    failed_submit = client.post(
        f"/api/simulation/drafts/{failed_draft.json()['draft']['draft_id']}/submit",
        json={},
        headers={**first_headers, "idempotency-key": "e2e-submit-before-confirm"},
    )
    assert failed_submit.status_code == 409
    assert failed_submit.json()["error"]["code"] == "USER_CONFIRMATION_REQUIRED"
    assert client.get("/api/simulation/orders", headers=first_headers).json() == []

    created = client.post(
        "/api/simulation/drafts",
        json=_draft_body(account["account_id"]),
        headers={**first_headers, "idempotency-key": "e2e-draft-complete"},
    )
    assert created.status_code == 201
    draft = created.json()
    reviewed = client.post(
        f"/api/simulation/drafts/{draft['draft']['draft_id']}/review",
        json={"expected_revision": draft["record_revision"]},
        headers=first_headers,
    )
    assert reviewed.status_code == 200
    review = reviewed.json()
    assert review["risk_result"]["status"] == "passed"
    assert review["risk_result"]["reason_hash"] == (
        "e3b0c44298fc1c149afbf4c8996fb924"
        "27ae41e4649b934ca495991b7852b855"
    )

    confirmed = client.post(
        f"/api/simulation/drafts/{draft['draft']['draft_id']}/confirm",
        json={
            "expected_revision": review["record_revision"],
            "seen_summary_hash": review["immutable_summary_hash"],
        },
        headers=first_headers,
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["draft"]["status"] == "confirmed"

    submitted = client.post(
        f"/api/simulation/drafts/{draft['draft']['draft_id']}/submit",
        json={},
        headers={**first_headers, "idempotency-key": "e2e-submit-complete"},
    )
    assert submitted.status_code == 201
    order = submitted.json()
    assert order["owner_id"] == first_user_id
    assert order["draft_reference"]["object_id"] == draft["draft"]["draft_id"]

    reread = client.get(
        f"/api/simulation/drafts/{draft['draft']['draft_id']}",
        headers=first_headers,
    )
    assert reread.status_code == 200
    assert reread.json()["draft"]["status"] == "confirmed"
    assert len(client.get("/api/simulation/orders", headers=first_headers).json()) == 1

    assert client.get(
        "/api/simulation/accounts/current",
        headers=second_headers,
    ).status_code == 404
    cross_user_draft = client.get(
        f"/api/simulation/drafts/{draft['draft']['draft_id']}",
        headers=second_headers,
    )
    assert cross_user_draft.status_code == 404
    assert cross_user_draft.json()["error"]["code"] == "NOT_FOUND"
    assert client.get("/api/simulation/orders", headers=second_headers).json() == []


async def _create_finance_schema(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.kw["bind"].begin() as connection:
        await connection.run_sync(FinanceBase.metadata.create_all)
