import httpx
import pytest

from bridge.finance_god.client import FinanceGodClient, FinanceGodError, project_snapshot


def test_projection_is_allowlisted_and_stable() -> None:
    result = project_snapshot(
        "plan-1",
        {
            "plan_id": "plan-1",
            "revision": 2,
            "status": "confirmed",
            "draft_id": "draft-1",
            "jwt": "secret",
        },
        {
            "draft": {"status": "confirmed"},
            "confirmed_at": "2026-07-25T12:00:00Z",
            "evidence": "do not store",
        },
    )
    assert result.usage == "context_only"
    assert result.asset_domain == "non_executable_asset_domain"
    assert "jwt" not in result.projection and "evidence" not in result.projection
    assert len(result.normalized_hash) == 64


@pytest.mark.asyncio
async def test_client_only_uses_allowlisted_gets() -> None:
    paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        assert request.method == "GET"
        if request.url.path.endswith("plan-1"):
            return httpx.Response(
                200,
                json={
                    "object": {
                        "plan_id": "plan-1",
                        "revision": 1,
                        "status": "confirmed",
                    },
                    "draft_links": [{"draft_id": "d-1"}],
                },
            )
        return httpx.Response(
            200,
            json={
                "draft": {"status": "confirmed"},
                "confirmed_at": "2026-07-25T12:00:00Z",
            },
        )

    client = FinanceGodClient(
        "http://finance-god", "token", httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    result = await client.fetch_snapshot("plan-1")
    assert result.draft_confirmed is True
    assert paths == ["/api/finance/trade-plans/plan-1", "/api/finance/simulation/drafts/d-1"]


def test_invalid_expiry_is_explicit() -> None:
    with pytest.raises(FinanceGodError):
        project_snapshot(
            "p",
            {
                "plan_id": "p",
                "revision": 1,
                "status": "confirmed",
                "expires_at": "nope",
            },
            None,
        )
