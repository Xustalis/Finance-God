"""P2 集成测试：注册边界校验、方向选择并发唯一性、AI 非法结构容错。

并发测试使用基于文件的 SQLite（每个请求独立连接），以真实触发
direction_recommendations 上的部分唯一索引
（uq_direction_recommendations_selected_one，profile_id WHERE selected）。
"""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.session import get_db
from app.main import app
from app.models import Base
from app.models.profile import DirectionRecommendation
from app.services.ai_orchestrator import get_ai_adapter_registry

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


# ---------------------------------------------------------------------------
# 1. 注册字段边界校验
# ---------------------------------------------------------------------------


def test_register_rejects_display_name_over_100_characters(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "display-name-101@example.com",
            "password": PASSWORD,
            "display_name": "x" * 101,
        },
    )

    assert response.status_code == 422


def test_register_accepts_display_name_at_100_characters(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "display-name-100@example.com",
            "password": PASSWORD,
            "display_name": "x" * 100,
        },
    )

    assert response.status_code == 201


def test_register_rejects_lowercase_base_currency(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "currency-lower@example.com",
            "password": PASSWORD,
            "base_currency": "cny",
        },
    )

    assert response.status_code == 422


def test_register_rejects_four_letter_base_currency(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "currency-long@example.com",
            "password": PASSWORD,
            "base_currency": "CNYY",
        },
    )

    assert response.status_code == 422


def test_register_rejects_malformed_region(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "region-bad@example.com",
            "password": PASSWORD,
            "region": "c1",
        },
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# 2. 方向选择并发唯一性（部分唯一索引）
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def file_session_factory(
    tmp_path: Path,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """基于临时文件的 SQLite：每个会话独立连接，具备真实事务隔离。"""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'boundary.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def async_client(
    file_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[httpx.AsyncClient]:
    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with file_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as test_client:
        yield test_client
    app.dependency_overrides.clear()


async def _completed_profile(
    async_client: httpx.AsyncClient, email: str
) -> tuple[dict[str, str], str, list[str]]:
    registered = await async_client.post(
        "/api/v1/auth/register", json={"email": email, "password": PASSWORD}
    )
    assert registered.status_code == 201
    headers = {
        "Authorization": f"Bearer {registered.json()['data']['access_token']}"
    }

    session = (
        await async_client.post("/api/v1/onboarding/sessions", headers=headers)
    ).json()["data"]
    updated = await async_client.put(
        f"/api/v1/onboarding/sessions/{session['id']}/objective-profile",
        headers=headers,
        json=adult_profile(),
    )
    assert updated.status_code == 200

    for number in range(6):
        turn = await async_client.post(
            f"/api/v1/onboarding/sessions/{session['id']}/messages",
            headers=headers,
            json={
                "content": f"I can stay invested and accept volatility, answer {number}",
                "input_mode": "text",
            },
        )
        assert turn.status_code == 200

    completed = await async_client.post(
        f"/api/v1/onboarding/sessions/{session['id']}/complete", headers=headers
    )
    assert completed.status_code == 200
    data = completed.json()["data"]
    directions = [item["direction"] for item in data["recommendations"]]
    return headers, data["profile"]["id"], directions


async def test_concurrent_direction_selection_keeps_single_selected_row(
    async_client: httpx.AsyncClient,
    file_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    headers, profile_id, directions = await _completed_profile(
        async_client, "concurrent-selection@example.com"
    )
    assert len(directions) == 5

    async def attempt_selection(direction: str) -> int:
        response = await async_client.post(
            f"/api/v1/profiles/{profile_id}/direction-selection",
            headers=headers,
            json={"selected_direction": direction},
        )
        return response.status_code

    statuses = await asyncio.gather(
        *(attempt_selection(direction) for direction in directions),
        return_exceptions=False,
    )

    # 至少一次成功；失败者只允许是并发冲突类错误（409/500），不允许 404/422
    assert 200 in statuses
    assert all(status in (200, 409, 500) for status in statuses)

    async with file_session_factory() as db:
        selected_count = await db.scalar(
            select(func.count())
            .select_from(DirectionRecommendation)
            .where(
                DirectionRecommendation.profile_id == profile_id,
                DirectionRecommendation.selected.is_(True),
            )
        )
    # 部分唯一索引保证：无论并发交错顺序如何，最终至多且恰有一条 selected
    assert selected_count == 1


# ---------------------------------------------------------------------------
# 3. mock AI 返回非法结构 → 502 且会话轮次状态不变
# ---------------------------------------------------------------------------


class _MalformedOrchestrator:
    async def respond(self, **kwargs):
        return {"reply": ""}


class _FixedRegistry:
    def __init__(self, orchestrator) -> None:
        self.orchestrator = orchestrator

    def resolve_text(self, **kwargs):
        return self.orchestrator


def test_malformed_ai_structure_returns_502_and_keeps_session_state(
    client: TestClient,
) -> None:
    registered = client.post(
        "/api/v1/auth/register",
        json={"email": "malformed-boundary@example.com", "password": PASSWORD},
    ).json()["data"]
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    session = client.post("/api/v1/onboarding/sessions", headers=headers).json()[
        "data"
    ]
    client.put(
        f"/api/v1/onboarding/sessions/{session['id']}/objective-profile",
        headers=headers,
        json=adult_profile(),
    )
    before = client.get("/api/v1/onboarding/sessions/current", headers=headers).json()[
        "data"
    ]

    app.dependency_overrides[get_ai_adapter_registry] = lambda: _FixedRegistry(
        _MalformedOrchestrator()
    )
    response = client.post(
        f"/api/v1/onboarding/sessions/{session['id']}/messages",
        headers=headers,
        json={"content": "A sufficiently detailed answer", "input_mode": "text"},
    )

    assert response.status_code == 502
    after = client.get("/api/v1/onboarding/sessions/current", headers=headers).json()[
        "data"
    ]
    assert after["round_count"] == before["round_count"] == 0
    assert after["turn_count"] == before["turn_count"] == 0
    assert after["status"] == before["status"] == "active"
    assert after["current_dimension"] == before["current_dimension"]
    assert after["current_question"] == before["current_question"]
