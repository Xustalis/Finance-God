import inspect
import json

import httpx
import pytest

import app.services.ai_orchestrator as ai


@pytest.mark.asyncio
async def test_httpx_runtime_supports_socks_proxy_environment(monkeypatch) -> None:
    monkeypatch.setenv("ALL_PROXY", "socks5://127.0.0.1:1080")
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)

    async with httpx.AsyncClient():
        pass


def test_reserved_provider_interfaces_are_explicit() -> None:
    text_provider = getattr(ai, "TextProvider", None)
    stt_adapter = getattr(ai, "SpeechToTextAdapter", None)
    tts_adapter = getattr(ai, "TextToSpeechAdapter", None)
    browser_stt = getattr(ai, "BrowserSpeechToTextAdapter", None)
    browser_tts = getattr(ai, "BrowserTextToSpeechAdapter", None)

    assert inspect.isabstract(text_provider)
    assert inspect.isabstract(stt_adapter)
    assert inspect.isabstract(tts_adapter)
    assert issubclass(browser_stt, stt_adapter)
    assert issubclass(browser_tts, tts_adapter)


def test_unknown_text_provider_is_rejected() -> None:
    registry_type = getattr(ai, "AIAdapterRegistry", None)
    assert registry_type is not None

    with pytest.raises(LookupError, match="No configured text adapter"):
        registry_type().resolve_text(
            provider="reserved-cloud",
            model_name="future-model",
            system_prompt="custom prompt version",
        )


@pytest.mark.asyncio
async def test_mock_questions_are_chinese_and_change_with_user_content() -> None:
    orchestrator = ai.DeterministicMockOrchestrator()
    common = {
        "round_count": 0,
        "turn_count": 1,
        "min_rounds": 6,
        "max_rounds": 12,
        "completeness": 0.45,
        "dimension_scores": {},
        "followup_counts": {},
        "skipped_dimensions": [],
        "current_dimension": "risk_tolerance",
    }

    salary = await orchestrator.respond(content="我担心工资中断后的生活安排", **common)
    family = await orchestrator.respond(content="我更在意家庭未来五年的支出", **common)

    assert salary.next_question != family.next_question
    assert "工资中断" in salary.next_question
    assert "家庭未来" in family.next_question
    assert salary.next_question_dimension == "liquidity_need"
    assert salary.retry_question
    assert "收益" not in salary.next_question
    assert "收益" not in salary.retry_question
    assert "？" not in salary.reply


def deepseek_response(content: dict) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": json.dumps(content)}}]},
    )


def test_system_prompt_requires_automatic_numeric_profile_analysis() -> None:
    assert "until the user confirms" not in ai.ONBOARDING_SYSTEM_PROMPT
    assert "neutral value 0" in ai.ONBOARDING_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_deepseek_provider_uses_fixed_openai_contract_and_parses_json() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content)
        return deepseek_response(
            {
                "reply": "谢谢你用生活中的例子说明。",
                "target_dimension": "risk_tolerance",
                "profile_value": 0.8,
                "confidence": 0.82,
                "should_continue": True,
                "end_reason": None,
                "next_question": "这笔钱最早可能在什么时候需要使用？",
                "next_question_dimension": "liquidity_need",
            }
        )

    provider = ai.DeepSeekTextProvider(
        api_key="test-secret",
        transport=httpx.MockTransport(handler),
    )
    orchestrator = provider.create(
        model_name="deepseek-v4-flash",
        system_prompt="system prompt",
    )
    result = await orchestrator.respond(
        content="我可以长期持有，也能接受一些波动",
        round_count=0,
        turn_count=1,
        min_rounds=6,
        max_rounds=12,
        completeness=0.45,
        dimension_scores={},
        followup_counts={},
        skipped_dimensions=[],
        current_dimension="risk_tolerance",
        objective_profile={"investment_experience": "none"},
    )

    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["authorization"] == "Bearer test-secret"
    assert captured["body"]["model"] == "deepseek-v4-flash"
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert result.profile_delta == {ai.ProfileDimension.RISK_TOLERANCE: 0.8}
    assert result.next_question_dimension is ai.ProfileDimension.LIQUIDITY_NEED


@pytest.mark.asyncio
async def test_deepseek_null_profile_value_is_stored_as_neutral() -> None:
    transport = httpx.MockTransport(
        lambda request: deepseek_response(
            {
                "reply": "我会换一个更容易回答的生活场景。",
                "target_dimension": "risk_tolerance",
                "profile_value": None,
                "confidence": 0,
                "should_continue": True,
                "end_reason": None,
                "next_question": "如果这笔钱暂时下跌，你更倾向等待还是卖出？",
                "next_question_dimension": "risk_tolerance",
            }
        )
    )
    orchestrator = ai.DeepSeekTextProvider(
        api_key="test-secret", transport=transport
    ).create(model_name="deepseek-v4-flash", system_prompt="system prompt")

    result = await orchestrator.respond(
        content="我还不太清楚",
        round_count=0,
        turn_count=1,
        min_rounds=6,
        max_rounds=12,
        completeness=0.4,
        dimension_scores={},
        followup_counts={},
        skipped_dimensions=[],
        current_dimension="risk_tolerance",
        objective_profile={"investment_experience": "none"},
    )

    assert result.profile_delta == {ai.ProfileDimension.RISK_TOLERANCE: 0}


@pytest.mark.asyncio
async def test_deepseek_provider_classifies_rate_limit_without_leaking_body() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(429, text="provider-secret-body", request=request)
    )
    provider = ai.DeepSeekTextProvider(api_key="test-secret", transport=transport)
    orchestrator = provider.create(
        model_name="deepseek-v4-flash",
        system_prompt="system prompt",
    )

    with pytest.raises(ai.AIProviderError, match="请求过于频繁") as raised:
        await orchestrator.respond(
            content="生活化回答",
            round_count=0,
            turn_count=1,
            min_rounds=6,
            max_rounds=12,
            completeness=0.45,
            dimension_scores={},
            followup_counts={},
            skipped_dimensions=[],
            current_dimension="risk_tolerance",
            objective_profile={"investment_experience": "none"},
        )

    assert raised.value.code == "DEEPSEEK_RATE_LIMITED"
    assert "provider-secret-body" not in str(raised.value)


def test_novice_prompt_uses_life_scenarios_without_scoring_lack_of_knowledge() -> None:
    prompt = ai.build_interview_context(
        {"investment_experience": "none", "age_range": "26-35"}
    )

    assert "生活化场景" in prompt
    assert "一次只问一个概念" in prompt
    assert "不把“不懂”视为低风险" in prompt
