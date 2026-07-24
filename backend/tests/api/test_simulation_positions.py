from __future__ import annotations

from decimal import Decimal

from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from finance_god.api.auth import AuthenticationError
from finance_god.api.simulation import (
    SimulationPositionView,
    create_simulation_routes,
)


class _Accounts:
    """Fake application returning one position for a known owner only."""

    async def positions(
        self, *, owner_id: str
    ) -> tuple[SimulationPositionView, ...]:
        if owner_id != "user-with-account":
            return ()
        return (
            SimulationPositionView(
                account_id=f"account-{owner_id}",
                instrument_id="000001.SZ",
                currency="CNY",
                long_quantity=Decimal("100"),
                settled_quantity=Decimal("100"),
                frozen_quantity=Decimal("0"),
                cost_rmb=Decimal("1150.00"),
                revision=3,
            ),
        )


def _app(owner_id: str | None) -> Starlette:
    async def resolve_owner(_request) -> str:
        if owner_id is None:
            raise AuthenticationError("valid Bearer authentication is required")
        return owner_id

    return Starlette(
        routes=[
            Mount(
                "/api/simulation",
                routes=create_simulation_routes(
                    execution=object(),
                    accounts=_Accounts(),
                    portfolio=object(),
                    decision_inbox=object(),
                    owner_resolver=resolve_owner,
                ),
            )
        ]
    )


def test_positions_endpoint_returns_projections_for_owner_with_account() -> None:
    with TestClient(_app("user-with-account")) as client:
        response = client.get("/api/simulation/accounts/current/positions")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    position = body[0]
    assert position["instrument_id"] == "000001.SZ"
    assert position["long_quantity"] == "100"
    assert position["cost_rmb"] == "1150.00"
    assert position["currency"] == "CNY"


def test_positions_endpoint_returns_empty_list_without_account() -> None:
    with TestClient(_app("user-without-account")) as client:
        response = client.get("/api/simulation/accounts/current/positions")

    assert response.status_code == 200
    assert response.json() == []


def test_positions_endpoint_rejects_unauthenticated_requests() -> None:
    with TestClient(_app(None)) as client:
        response = client.get("/api/simulation/accounts/current/positions")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
