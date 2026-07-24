from __future__ import annotations

from decimal import Decimal

from server import _authenticated_owner
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from app.core.security import create_access_token
from finance_god.api.simulation import SimulationAccountView, create_simulation_routes


class _Accounts:
    async def current(self, *, owner_id: str) -> SimulationAccountView:
        return SimulationAccountView(
            account_id=f"account-{owner_id}",
            owner_id=owner_id,
            status="active",
            cash_total_rmb=Decimal("100000"),
            cash_available_rmb=Decimal("100000"),
            cash_frozen_rmb=Decimal("0"),
            margin_rmb=Decimal("0"),
            revision=1,
        )


def test_simulation_routes_use_jwt_subject_and_ignore_owner_header() -> None:
    app = Starlette(
        routes=[
            Mount(
                "/api/simulation",
                routes=create_simulation_routes(
                    execution=object(),
                    accounts=_Accounts(),
                    portfolio=object(),
                    decision_inbox=object(),
                    owner_resolver=_authenticated_owner,
                ),
            )
        ]
    )
    first_token = create_access_token("user-a")
    second_token = create_access_token("user-b")

    with TestClient(app) as client:
        first = client.get(
            "/api/simulation/accounts/current",
            headers={
                "Authorization": f"Bearer {first_token}",
                "x-finance-god-owner-id": "user-b",
            },
        )
        second = client.get(
            "/api/simulation/accounts/current",
            headers={"Authorization": f"Bearer {second_token}"},
        )

    assert first.status_code == 200
    assert first.json()["owner_id"] == "user-a"
    assert second.status_code == 200
    assert second.json()["owner_id"] == "user-b"


def test_simulation_routes_reject_missing_and_invalid_tokens() -> None:
    app = Starlette(
        routes=[
            Mount(
                "/api/simulation",
                routes=create_simulation_routes(
                    execution=object(),
                    accounts=_Accounts(),
                    portfolio=object(),
                    decision_inbox=object(),
                    owner_resolver=_authenticated_owner,
                ),
            )
        ]
    )

    with TestClient(app) as client:
        missing = client.get("/api/simulation/accounts/current")
        invalid = client.get(
            "/api/simulation/accounts/current",
            headers={"Authorization": "Bearer invalid"},
        )

    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "UNAUTHORIZED"
    assert invalid.status_code == 401
    assert invalid.json()["error"]["code"] == "UNAUTHORIZED"
