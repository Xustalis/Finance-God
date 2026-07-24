"""对话质量集成测试：question_history 累积去重、history/asked/emotion 透传、兜底去重。"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.main import app
from app.models.onboarding import OnboardingSession, ProfileMessage
from app.services.ai_orchestrator import (
    INITIAL_RISK_QUESTION,
    get_ai_adapter_registry,
    projected_next_dimension,
)
from app.services.question_bank import select_question


def ready_session(client: TestClient, email: str) -> tuple[dict[str, str], str]:
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
            "age_range": "26-35",
            "asset_level": "A4",
            "employment_status": "employed",
            "income_range": "I4",
            "debt_pressure": "low",
            "emergency_fund_months": 6,
            "investment_experience": "beginner",
            "fund_horizon": "3_5_years",
            "loss_reaction": "hold",
        },
    )
    return headers, session["id"]


class FixedRegistry:
    def __init__(self, orchestrator):
        self.orchestrator = orchestrator

    def resolve_text(self, **kwargs):
        return self.orchestrator


class CapturingOrchestrator:
    """确定性 stub：记录 respond 收到的关键参数，并沿服务端投影推进维度。"""

    def __init__(self):
        self.calls: list[dict] = []

    async def respond(
        self,
        *,
        content,
        round_count,
        turn_count,
        min_rounds,
        max_rounds,
        completeness,
        dimension_scores,
        followup_counts,
        skipped_dimensions,
        current_dimension,
        objective_profile=None,
        history=None,
        asked_questions=None,
        emotion=None,
    ):
        self.calls.append(
            {
                "content": content,
                "current_dimension": current_dimension,
                "history": history,
                "asked_questions": asked_questions,
                "emotion": emotion,
            }
        )
        next_dimension = projected_next_dimension(
            current_dimension=current_dimension,
            confidence=0.9,
            round_count=round_count,
            min_rounds=min_rounds,
            dimension_scores=dimension_scores,
            followup_counts=followup_counts,
            skipped_dimensions=skipped_dimensions,
        )
        should_continue = turn_count < max_rounds and next_dimension is not None
        return {
            "reply": f"我理解你的意思，会把这条信息记下来（第{turn_count}轮）。",
            "target_dimension": current_dimension,
            "sensitive": current_dimension == "income_stability",
            "profile_delta": {current_dimension: 0.5},
            "confidence": 0.9,
            "should_continue": should_continue,
            "end_reason": None if should_continue else "sufficient_profile",
            "next_question": (
                select_question(
                    next_dimension,
                    asked_questions=asked_questions,
                    user_excerpt=content,
                )
                if should_continue
                else None
            ),
            "next_question_dimension": next_dimension if should_continue else None,
            "retry_question": "换个角度再聊聊这个话题。",
        }


class MismatchedDimensionOrchestrator:
    """始终返回与服务端投影不符的下一维度，强制走服务端兜底补问。"""

    async def respond(self, **kwargs):
        current = kwargs["current_dimension"]
        return {
            "reply": "我先把这条信息记下来。",
            "target_dimension": current,
            "sensitive": current == "income_stability",
            "profile_delta": {current: 0.1},
            "confidence": 0.4,
            "should_continue": True,
            "end_reason": None,
            "next_question": "接下来想聊聊你的投资目标。",
            "next_question_dimension": "loss_behavior",
            "retry_question": "换个角度再聊聊这个话题。",
        }


@pytest.mark.asyncio
async def test_question_history_accumulates_without_duplicates(
    client: TestClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    headers, session_id = ready_session(client, "quality-history@example.com")
    orchestrator = CapturingOrchestrator()
    app.dependency_overrides[get_ai_adapter_registry] = lambda: FixedRegistry(orchestrator)

    history_lengths: list[int] = []
    for number in range(6):
        turn = client.post(
            f"/api/v1/onboarding/sessions/{session_id}/messages",
            headers=headers,
            json={"content": f"这是我的第{number}条真实回答，内容足够长。"},
        )
        assert turn.status_code == 200
        async with session_factory() as db:
            session = await db.get(OnboardingSession, session_id)
            history_lengths.append(len(session.question_history))

    async with session_factory() as db:
        session = await db.get(OnboardingSession, session_id)
        entries = session.question_history

    # 初始问题 round 0 + 前 5 轮各追加一条；最后一轮 ready 不再追加
    assert history_lengths == [2, 3, 4, 5, 6, 6]
    assert entries[0] == {
        "round": 0,
        "dimension": "risk_tolerance",
        "question": INITIAL_RISK_QUESTION,
    }
    assert [item["round"] for item in entries] == [0, 1, 2, 3, 4, 5]
    questions = [item["question"] for item in entries]
    assert len(questions) == len(set(questions)), "question_history 中的问题文本不得重复"


@pytest.mark.asyncio
async def test_respond_receives_history_asked_questions_and_emotion(
    client: TestClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    headers, session_id = ready_session(client, "quality-context@example.com")
    orchestrator = CapturingOrchestrator()
    app.dependency_overrides[get_ai_adapter_registry] = lambda: FixedRegistry(orchestrator)

    first_content = "我平时都是按计划定投的"
    first = client.post(
        f"/api/v1/onboarding/sessions/{session_id}/messages",
        headers=headers,
        json={"content": first_content},
    )
    assert first.status_code == 200
    first_reply = first.json()["data"]["assistant_message"]["content"]
    first_next_question = first.json()["data"]["turn"]["next_question"]

    anxious_content = "最近有点纠结，晚上都睡不着"
    second = client.post(
        f"/api/v1/onboarding/sessions/{session_id}/messages",
        headers=headers,
        json={"content": anxious_content},
    )
    assert second.status_code == 200

    assert len(orchestrator.calls) == 2
    first_call, second_call = orchestrator.calls

    # 第一轮：无历史消息，asked_questions 含初始问题
    assert first_call["history"] == []
    assert first_call["asked_questions"] == [INITIAL_RISK_QUESTION]
    assert first_call["emotion"]["emotion"] == "calm"

    # 第二轮：history 含此前 user/assistant 消息，asked_questions 追加了上一轮问题
    assert second_call["history"] == [
        {"role": "user", "content": first_content},
        {"role": "assistant", "content": first_reply},
    ]
    assert second_call["asked_questions"] == [INITIAL_RISK_QUESTION, first_next_question]
    # 含焦虑关键词的输入被词典识别为 anxiety
    assert second_call["emotion"]["emotion"] == "anxiety"
    assert second_call["emotion"]["score"] > 0.5

    # emotion 已随成功路径写入 user_message.extracted_data
    async with session_factory() as db:
        stored = await db.scalar(
            select(ProfileMessage).where(
                ProfileMessage.session_id == session_id,
                ProfileMessage.role == "user",
                ProfileMessage.content == anxious_content,
            )
        )
        assert stored is not None
        assert stored.extracted_data["emotion"]["emotion"] == "anxiety"


@pytest.mark.asyncio
async def test_fallback_questions_for_same_dimension_do_not_repeat(
    client: TestClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    headers, session_id = ready_session(client, "quality-fallback@example.com")
    app.dependency_overrides[get_ai_adapter_registry] = lambda: FixedRegistry(
        MismatchedDimensionOrchestrator()
    )

    first = client.post(
        f"/api/v1/onboarding/sessions/{session_id}/messages",
        headers=headers,
        json={"content": "第一条不太确定的回答"},
    )
    assert first.status_code == 200
    first_state = first.json()["data"]["session"]
    # 低置信度：风险维度兜底补问（与初始问题同维度但文本不同）
    assert first_state["current_dimension"] == "risk_tolerance"
    first_question = first_state["current_question"]
    assert first_question != INITIAL_RISK_QUESTION
    
    second = client.post(
        f"/api/v1/onboarding/sessions/{session_id}/messages",
        headers=headers,
        json={"content": "第二条依然模糊的回答"},
    )
    assert second.status_code == 200
    second_state = second.json()["data"]["session"]
    # 风险维度已问满两次，投影推进到 liquidity_need，第一次兜底
    assert second_state["current_dimension"] == "liquidity_need"
    second_question = second_state["current_question"]
    
    third = client.post(
        f"/api/v1/onboarding/sessions/{session_id}/messages",
        headers=headers,
        json={"content": "第三条还是说不清楚的回答"},
    )
    assert third.status_code == 200
    third_state = third.json()["data"]["session"]
    # liquidity_need 的第二次兜底：同维度两次兜底问题文本必须不同
    assert third_state["current_dimension"] == "liquidity_need"
    third_question = third_state["current_question"]
    assert second_question != third_question
    
    async with session_factory() as db:
        session = await db.get(OnboardingSession, session_id)
        questions = [item["question"] for item in session.question_history]
    assert questions == [INITIAL_RISK_QUESTION, first_question, second_question, third_question]
    assert len(questions) == len(set(questions))
