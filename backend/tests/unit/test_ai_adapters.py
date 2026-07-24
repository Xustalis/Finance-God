import inspect

import pytest

import app.services.ai_orchestrator as ai


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
