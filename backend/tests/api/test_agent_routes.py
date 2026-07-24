from __future__ import annotations

from types import SimpleNamespace

from research_runtime.contracts import AgentRequest
from research_runtime.models import EvidenceRecord
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from finance_god.api.agent_routes import create_agent_routes

OWNER = "profile-owner"
AUTH = {"Authorization": "Bearer token"}

PROFILE = {
    "version": 3,
    "archetype_code": "growth_seeker",
    "archetype_title": "成长进取型",
    "risk_level": "aggressive",
    "loss_tolerance_percent": 25,
    "confidence": 0.82,
    "completeness": 0.9,
    "education_only": False,
    "objective_profile": {"asset_level": "A6"},
    "dimension_scores": {"risk_capacity": 0.7},
    "recommended_directions": ["equities", "public_funds"],
    "selected_direction": "equities",
}


class _CapturingRuntime:
    """Duck-typed runtime that records the request it was asked to run."""

    def __init__(self) -> None:
        self.last_request: AgentRequest | None = None

    async def run(self, request: AgentRequest):
        self.last_request = request
        return SimpleNamespace(
            model_dump=lambda mode="json": {"run_id": request.run_id, "results": []}
        )

    def list_agents(self) -> tuple:
        return ()


async def _resolve_owner(_request) -> str:
    return OWNER


def _client(
    runtime: _CapturingRuntime,
    profile: dict | None,
    learning: list[EvidenceRecord] | None = None,
    *,
    learning_error: bool = False,
):
    async def _runtime_provider() -> _CapturingRuntime:
        return runtime

    async def _profile_provider(owner_id: str) -> dict | None:
        assert owner_id == OWNER
        return profile

    async def _learning_provider(
        subject: str,
        task_type: str,
        asset_kind: str,
    ) -> list[EvidenceRecord]:
        assert subject
        assert task_type
        assert asset_kind
        if learning_error:
            raise RuntimeError("learning sidecar unavailable")
        return learning or []

    app = Starlette(
        routes=[
            Mount(
                "/agent",
                routes=create_agent_routes(
                    runtime_provider=_runtime_provider,
                    owner_resolver=_resolve_owner,
                    profile_provider=_profile_provider,
                    learning_context_provider=_learning_provider,
                ),
            )
        ]
    )
    return TestClient(app)


def test_profile_is_injected_into_payload_and_evidence() -> None:
    runtime = _CapturingRuntime()
    client = _client(runtime, PROFILE)

    response = client.post(
        "/agent/research",
        json={"subject": "600519", "task_type": "research", "asset_kind": "equity"},
        headers=AUTH,
    )

    assert response.status_code == 200
    request = runtime.last_request
    assert request is not None
    # The planner and every prompt agent receive the profile as basic context.
    assert request.payload["investor_profile"]["risk_level"] == "aggressive"
    assert request.payload["investor_profile"]["selected_direction"] == "equities"
    # A citable profile evidence record is prepended for research claims.
    profile_evidence = [e for e in request.evidence if e.identifier == "investor-profile"]
    assert len(profile_evidence) == 1
    assert "aggressive" in profile_evidence[0].excerpt


def test_run_proceeds_without_profile() -> None:
    runtime = _CapturingRuntime()
    client = _client(runtime, None)

    response = client.post(
        "/agent/research",
        json={"subject": "600519", "task_type": "research"},
        headers=AUTH,
    )

    assert response.status_code == 200
    request = runtime.last_request
    assert request is not None
    assert "investor_profile" not in request.payload
    assert all(e.identifier != "investor-profile" for e in request.evidence)


def test_verified_learning_context_is_injected_as_citable_evidence() -> None:
    runtime = _CapturingRuntime()
    learned = EvidenceRecord(
        identifier="L-VERIFIED",
        source="learning:strategy_backtest",
        excerpt="[verified:outcome] held-out result",
    )
    client = _client(runtime, None, [learned])

    response = client.post(
        "/agent/research",
        json={"subject": "510300.SH", "task_type": "research"},
        headers=AUTH,
    )

    assert response.status_code == 200
    request = runtime.last_request
    assert request is not None
    assert [item.identifier for item in request.evidence] == ["L-VERIFIED"]


def test_learning_failure_does_not_block_product_agent() -> None:
    runtime = _CapturingRuntime()
    client = _client(runtime, None, learning_error=True)

    response = client.post(
        "/agent/research",
        json={"subject": "600519.SH", "task_type": "research"},
        headers=AUTH,
    )

    assert response.status_code == 200
    assert runtime.last_request is not None
    assert runtime.last_request.evidence == []


def test_caller_evidence_keeps_priority_at_agent_contract_limit() -> None:
    runtime = _CapturingRuntime()
    learned = EvidenceRecord(
        identifier="L-VERIFIED",
        source="learning:test",
        excerpt="verified",
    )
    client = _client(runtime, PROFILE, [learned])
    evidence = [
        {
            "identifier": f"caller-{index}",
            "source": "caller",
            "excerpt": "fact",
        }
        for index in range(50)
    ]

    response = client.post(
        "/agent/research",
        json={"subject": "510300.SH", "evidence": evidence},
        headers=AUTH,
    )

    assert response.status_code == 200
    request = runtime.last_request
    assert request is not None
    assert len(request.evidence) == 50
    assert all(item.identifier.startswith("caller-") for item in request.evidence)
