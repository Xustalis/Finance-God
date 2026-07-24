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


def deepseek_raw_response(raw_content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": raw_content}}]},
    )


DEEPSEEK_RESPOND_ARGS = {
    "content": "我可以长期持有，也能接受一些波动",
    "round_count": 0,
    "turn_count": 1,
    "min_rounds": 6,
    "max_rounds": 12,
    "completeness": 0.45,
    "dimension_scores": {},
    "followup_counts": {},
    "skipped_dimensions": [],
    "current_dimension": "risk_tolerance",
    "objective_profile": {"investment_experience": "none"},
}


def deepseek_orchestrator(transport: httpx.MockTransport) -> ai.AIOrchestrator:
    return ai.DeepSeekTextProvider(api_key="test-secret", transport=transport).create(
        model_name="deepseek-v4-flash", system_prompt="system prompt"
    )


@pytest.mark.asyncio
async def test_deepseek_content_wrapped_in_markdown_fence_is_parsed() -> None:
    payload = json.dumps(
        {
            "reply": "谢谢你的分享。",
            "target_dimension": "risk_tolerance",
            "profile_value": 0.5,
            "confidence": 0.7,
            "should_continue": True,
            "end_reason": None,
            "next_question": "这笔钱多久内可能需要取用？",
            "next_question_dimension": "liquidity_need",
        },
        ensure_ascii=False,
    )
    transport = httpx.MockTransport(
        lambda request: deepseek_raw_response(f"```json\n{payload}\n```")
    )

    result = await deepseek_orchestrator(transport).respond(**DEEPSEEK_RESPOND_ARGS)

    assert result.reply == "谢谢你的分享。"
    assert result.next_question_dimension is ai.ProfileDimension.LIQUIDITY_NEED


@pytest.mark.asyncio
async def test_deepseek_content_with_surrounding_prose_is_parsed() -> None:
    payload = json.dumps(
        {
            "reply": "已记录你的情况。",
            "target_dimension": "risk_tolerance",
            "profile_value": 0.2,
            "confidence": 0.6,
            "should_continue": True,
            "next_question": "你最希望这笔资金支持哪个目标？",
            "next_question_dimension": "investment_goal",
        },
        ensure_ascii=False,
    )
    transport = httpx.MockTransport(
        lambda request: deepseek_raw_response(f"以下是结构化结果：{payload}\n希望对你有帮助。")
    )

    result = await deepseek_orchestrator(transport).respond(**DEEPSEEK_RESPOND_ARGS)

    assert result.reply == "已记录你的情况。"
    assert result.next_question_dimension is ai.ProfileDimension.INVESTMENT_GOAL


@pytest.mark.asyncio
async def test_deepseek_unknown_dimensions_are_normalized() -> None:
    transport = httpx.MockTransport(
        lambda request: deepseek_response(
            {
                "reply": "接下来聊聊你的财务目标。",
                "target_dimension": "financial_goal",
                "profile_value": 0.7,
                "confidence": 0.8,
                "should_continue": True,
                "end_reason": "continue",
                "next_question": "你的投资计划是长期还是短期？",
                "next_question_dimension": "investment_horizon",
            }
        )
    )

    result = await deepseek_orchestrator(transport).respond(**DEEPSEEK_RESPOND_ARGS)

    # 本轮证据归属会话当前维度，枚举外的下一问题维度置空由服务端兜底
    assert result.target_dimension is ai.ProfileDimension.RISK_TOLERANCE
    assert result.profile_delta == {ai.ProfileDimension.RISK_TOLERANCE: 0.7}
    assert result.next_question is None
    assert result.next_question_dimension is None


@pytest.mark.asyncio
async def test_deepseek_missing_optional_fields_use_safe_defaults() -> None:
    transport = httpx.MockTransport(
        lambda request: deepseek_response(
            {
                "reply": "我会换一个更容易回答的问题。",
                "target_dimension": "risk_tolerance",
            }
        )
    )

    result = await deepseek_orchestrator(transport).respond(**DEEPSEEK_RESPOND_ARGS)

    assert result.profile_delta == {ai.ProfileDimension.RISK_TOLERANCE: 0.0}
    assert result.confidence == 0.5
    assert result.should_continue is True
    assert result.next_question is None
    assert result.next_question_dimension is None


@pytest.mark.asyncio
async def test_deepseek_out_of_range_scores_are_clamped() -> None:
    transport = httpx.MockTransport(
        lambda request: deepseek_response(
            {
                "reply": "已记录。",
                "target_dimension": "risk_tolerance",
                "profile_value": 1.6,
                "confidence": 1.4,
                "should_continue": True,
            }
        )
    )

    result = await deepseek_orchestrator(transport).respond(**DEEPSEEK_RESPOND_ARGS)

    assert result.profile_delta == {ai.ProfileDimension.RISK_TOLERANCE: 1.0}
    assert result.confidence == 1.0


@pytest.mark.asyncio
async def test_deepseek_string_numeric_scores_are_parsed_and_clamped() -> None:
    transport = httpx.MockTransport(
        lambda request: deepseek_response(
            {
                "reply": "已记录。",
                "target_dimension": "risk_tolerance",
                "profile_value": "0.7",
                "confidence": "0.8",
                "should_continue": True,
            }
        )
    )

    result = await deepseek_orchestrator(transport).respond(**DEEPSEEK_RESPOND_ARGS)

    assert result.profile_delta == {ai.ProfileDimension.RISK_TOLERANCE: 0.7}
    assert result.confidence == 0.8


@pytest.mark.asyncio
async def test_deepseek_non_numeric_profile_value_keeps_readable_error() -> None:
    transport = httpx.MockTransport(
        lambda request: deepseek_response(
            {
                "reply": "已记录。",
                "target_dimension": "risk_tolerance",
                "profile_value": "not-a-number",
                "confidence": 0.8,
                "should_continue": True,
            }
        )
    )

    with pytest.raises(ai.AIProviderError, match="无法解析的结构化结果") as raised:
        await deepseek_orchestrator(transport).respond(**DEEPSEEK_RESPOND_ARGS)

    assert raised.value.code == "DEEPSEEK_INVALID_RESPONSE"


@pytest.mark.asyncio
async def test_deepseek_severely_out_of_range_scores_are_rejected() -> None:
    # 严重越界是模型硬失败，不应被 clamp 静默截断入库
    for overrides in ({"profile_value": 10}, {"confidence": -5}):
        transport = httpx.MockTransport(
            lambda request, overrides=overrides: deepseek_response(
                {
                    "reply": "已记录。",
                    "target_dimension": "risk_tolerance",
                    "profile_value": 0.5,
                    "confidence": 0.8,
                    "should_continue": True,
                    **overrides,
                }
            )
        )

        with pytest.raises(ai.AIProviderError, match="无法解析的结构化结果") as raised:
            await deepseek_orchestrator(transport).respond(**DEEPSEEK_RESPOND_ARGS)

        assert raised.value.code == "DEEPSEEK_INVALID_RESPONSE"


@pytest.mark.asyncio
async def test_deepseek_slightly_out_of_range_scores_are_clamped_to_bounds() -> None:
    transport = httpx.MockTransport(
        lambda request: deepseek_response(
            {
                "reply": "已记录。",
                "target_dimension": "risk_tolerance",
                "profile_value": 1.05,
                "confidence": -0.05,
                "should_continue": True,
            }
        )
    )

    result = await deepseek_orchestrator(transport).respond(**DEEPSEEK_RESPOND_ARGS)

    assert result.profile_delta == {ai.ProfileDimension.RISK_TOLERANCE: 1.0}
    assert result.confidence == 0.0


@pytest.mark.asyncio
async def test_deepseek_blank_next_question_is_normalized_to_none() -> None:
    transport = httpx.MockTransport(
        lambda request: deepseek_response(
            {
                "reply": "已记录。",
                "target_dimension": "risk_tolerance",
                "profile_value": 0.5,
                "confidence": 0.7,
                "should_continue": True,
                "next_question": "   \n",
                "next_question_dimension": "liquidity_need",
            }
        )
    )

    result = await deepseek_orchestrator(transport).respond(**DEEPSEEK_RESPOND_ARGS)

    assert result.next_question is None
    assert result.next_question_dimension is None


@pytest.mark.asyncio
async def test_deepseek_blank_reply_keeps_readable_error() -> None:
    transport = httpx.MockTransport(
        lambda request: deepseek_response(
            {
                "reply": "   ",
                "target_dimension": "risk_tolerance",
                "profile_value": 0.5,
                "confidence": 0.7,
                "should_continue": True,
            }
        )
    )

    with pytest.raises(ai.AIProviderError, match="无法解析的结构化结果") as raised:
        await deepseek_orchestrator(transport).respond(**DEEPSEEK_RESPOND_ARGS)

    assert raised.value.code == "DEEPSEEK_INVALID_RESPONSE"


@pytest.mark.asyncio
async def test_deepseek_non_enum_end_reason_is_tolerated() -> None:
    transport = httpx.MockTransport(
        lambda request: deepseek_response(
            {
                "reply": "已记录。",
                "target_dimension": "risk_tolerance",
                "profile_value": 0.5,
                "confidence": 0.7,
                "should_continue": True,
                "end_reason": "continue",
            }
        )
    )

    result = await deepseek_orchestrator(transport).respond(**DEEPSEEK_RESPOND_ARGS)

    assert result.end_reason == "continue"
    assert result.should_continue is True


@pytest.mark.asyncio
async def test_deepseek_unparseable_content_keeps_readable_error() -> None:
    transport = httpx.MockTransport(
        lambda request: deepseek_raw_response("抱歉，我无法提供结构化结果。")
    )

    with pytest.raises(ai.AIProviderError, match="无法解析的结构化结果") as raised:
        await deepseek_orchestrator(transport).respond(**DEEPSEEK_RESPOND_ARGS)

    assert raised.value.code == "DEEPSEEK_INVALID_RESPONSE"


def test_extract_json_object_handles_fences_and_prefixes() -> None:
    assert ai.extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert ai.extract_json_object('```\n{"a": 1}\n```') == {"a": 1}
    assert ai.extract_json_object('前缀说明 {"a": {"b": 2}} 后缀说明') == {"a": {"b": 2}}
    with pytest.raises(json.JSONDecodeError):
        ai.extract_json_object("完全不含结构化内容")


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


def test_profile_snapshot_lists_uncertain_dimensions_and_asked_questions() -> None:
    snapshot = ai.build_profile_snapshot(
        objective_profile={"age_range": "36-45", "fund_horizon": "5_plus_years"},
        dimension_scores={"risk_tolerance": 0.7},
        followup_counts={"liquidity_need": 1},
        skipped_dimensions=["income_stability"],
        asked_questions=["你能接受多大波动？"],
    )

    assert "风险承受" in snapshot
    # 已较清楚（高置信或已跳过）与仍不确定分开列出
    assert "收入稳定性(已跳过)" in snapshot
    assert "流动性需求(已问1次)" in snapshot
    assert "你能接受多大波动？" in snapshot


@pytest.mark.asyncio
async def test_mock_opening_question_is_deterministic_and_life_anchored() -> None:
    orchestrator = ai.DeterministicMockOrchestrator()

    question, dimension = await orchestrator.opening_question(
        objective_profile={"investment_experience": "none"}
    )

    assert dimension is ai.ProfileDimension.RISK_TOLERANCE
    assert question == ai.INITIAL_RISK_QUESTION
    assert "阶段性亏损" in question


@pytest.mark.asyncio
async def test_deepseek_opening_question_parses_structure_and_snapshot() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return deepseek_response(
            {
                "opening_question": "这笔钱对你来说，最重要的是能帮你完成什么？",
                "dimension": "investment_goal",
            }
        )

    orchestrator = ai.DeepSeekTextProvider(
        api_key="test-secret",
        transport=httpx.MockTransport(handler),
    ).create(model_name="deepseek-v4-flash", system_prompt="system prompt")

    question, dimension = await orchestrator.opening_question(
        objective_profile={"age_range": "36-45", "fund_horizon": "5_plus_years"}
    )

    assert question == "这笔钱对你来说，最重要的是能帮你完成什么？"
    assert dimension is ai.ProfileDimension.INVESTMENT_GOAL
    # 开场请求体也携带了画像快照（供 AI 据此定制开场问题）
    user_message = captured["body"]["messages"][-1]["content"]
    assert "用户当前画像快照" in user_message


@pytest.mark.asyncio
async def test_deepseek_opening_question_invalid_dimension_defaults_to_first() -> None:
    transport = httpx.MockTransport(
        lambda request: deepseek_response(
            {"opening_question": "先聊聊你对这笔钱的打算吧？", "dimension": "financial_goal"}
        )
    )
    orchestrator = ai.DeepSeekTextProvider(
        api_key="test-secret", transport=transport
    ).create(model_name="deepseek-v4-flash", system_prompt="system prompt")

    question, dimension = await orchestrator.opening_question(objective_profile={})

    assert question == "先聊聊你对这笔钱的打算吧？"
    # 非法维度归一化为第一维度（风险承受）
    assert dimension is ai.ProfileDimension.RISK_TOLERANCE
