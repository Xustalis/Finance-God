from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from finance_god.api.simulation import create_simulation_routes
from finance_god.domain import VersionReference


TRUSTED_VERSION = VersionReference(
    object_type="market_quote",
    object_id="000001.SZ",
    version="2026-07-24T15:00:00+08:00",
)


class _Execution:
    def __init__(self) -> None:
        self.created: dict[str, object] | None = None

    async def create_order_draft(self, **kwargs: object) -> dict[str, object]:
        self.created = kwargs
        return {"created": True}


async def _owner(_request) -> str:
    return "user-1"


async def _trusted_reference(_symbol: str) -> tuple[Decimal, VersionReference]:
    return Decimal("11.10"), TRUSTED_VERSION


def _app(execution: _Execution) -> Starlette:
    return Starlette(
        routes=[
            Mount(
                "/api/simulation",
                routes=create_simulation_routes(
                    execution=execution,
                    accounts=object(),
                    portfolio=object(),
                    decision_inbox=object(),
                    owner_resolver=_owner,
                    market_reference_provider=_trusted_reference,
                ),
            )
        ]
    )


def _draft_body(*, price: str, version: str) -> dict[str, object]:
    return {
        "mode": "manual",
        "account_id": "account-1",
        "instrument_id": "000001.SZ",
        "side": "buy",
        "order_type": "market",
        "quantity": "100",
        "amount": None,
        "limit_price": None,
        "reference_price": price,
        "time_in_force": "day",
        "fund_rule_version": None,
        "valid_until": (datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
        "input_versions": [
            {
                "object_type": "market_quote",
                "object_id": "000001.SZ",
                "version": version,
            }
        ],
        "plan_reference": None,
    }


def test_draft_uses_the_server_market_reference() -> None:
    execution = _Execution()
    with TestClient(_app(execution)) as client:
        response = client.post(
            "/api/simulation/drafts",
            json=_draft_body(
                price="11.10",
                version=TRUSTED_VERSION.version,
            ),
            headers={"Idempotency-Key": "draft-trusted-1"},
        )

    assert response.status_code == 201
    assert execution.created is not None
    assert execution.created["reference_price"] == Decimal("11.10")
    assert execution.created["input_versions"] == (TRUSTED_VERSION,)


def test_draft_rejects_a_browser_price_that_no_longer_matches() -> None:
    execution = _Execution()
    with TestClient(_app(execution)) as client:
        response = client.post(
            "/api/simulation/drafts",
            json=_draft_body(
                price="9.99",
                version=TRUSTED_VERSION.version,
            ),
            headers={"Idempotency-Key": "draft-tampered-1"},
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    assert execution.created is None
