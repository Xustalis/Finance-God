"""emotion_lexicon 模块单元测试。"""

from __future__ import annotations

import json

import pytest

from app.services.emotion_lexicon import AROUSAL_MAP, EMOTION_KEYWORDS, VALENCE_MAP, analyze

ALL_EMOTIONS = {"greed", "optimism", "calm", "anxiety", "frustration", "panic"}

TYPICAL_SENTENCES = {
    "greed": "现在行情这么猛，我想全仓梭哈，再不买就晚了！",
    "optimism": "我还是看好后市，对手里的基金有信心，拿得住。",
    "calm": "这只是正常波动，我会按计划定投，保持平常心。",
    "anxiety": "最近有点纠结，晚上睡不着，心里没底，不知道怎么办。",
    "frustration": "亏麻了，真后悔，早知道就不买了，现在心灰意冷。",
    "panic": "跌成这样我吓死了，赶紧卖了割肉吧，感觉要崩盘了！",
}


def test_lexicon_structure() -> None:
    assert set(EMOTION_KEYWORDS) == ALL_EMOTIONS
    assert set(AROUSAL_MAP) == ALL_EMOTIONS
    assert set(VALENCE_MAP) == ALL_EMOTIONS
    for emotion, keywords in EMOTION_KEYWORDS.items():
        assert 10 <= len(keywords) <= 15, emotion
        for keyword, weight in keywords.items():
            assert keyword.strip()
            assert 0.0 < weight <= 1.0


@pytest.mark.parametrize("emotion", sorted(ALL_EMOTIONS))
def test_typical_sentence_detected(emotion: str) -> None:
    result = analyze(TYPICAL_SENTENCES[emotion])
    assert result["emotion"] == emotion
    assert result["source"] == "lexicon"
    assert result["matched_keywords"], emotion
    assert result["score"] > 0.0
    assert result["confidence"] > 0.0


def test_no_match_returns_calm_zero() -> None:
    result = analyze("今天中午吃什么好呢")
    assert result["emotion"] == "calm"
    assert result["score"] == 0.0
    assert result["confidence"] == 0.0
    assert result["valence"] == 0.0
    assert result["matched_keywords"] == []
    assert result["source"] == "lexicon"


def test_empty_text_returns_calm_zero() -> None:
    result = analyze("")
    assert result["emotion"] == "calm"
    assert result["score"] == 0.0
    assert result["confidence"] == 0.0


def test_value_ranges() -> None:
    samples = list(TYPICAL_SENTENCES.values()) + ["随便聊聊天气", ""]
    for text in samples:
        result = analyze(text)
        assert result["emotion"] in ALL_EMOTIONS
        assert 0.0 <= result["score"] <= 1.0
        assert 0.0 <= result["arousal"] <= 1.0
        assert -1.0 <= result["valence"] <= 1.0
        assert 0.0 <= result["confidence"] <= 1.0


def test_arousal_valence_follow_mapping() -> None:
    for emotion, sentence in TYPICAL_SENTENCES.items():
        result = analyze(sentence)
        assert result["arousal"] == AROUSAL_MAP[emotion]
        assert result["valence"] == pytest.approx(VALENCE_MAP[emotion] * result["score"])


def test_result_json_serializable() -> None:
    for text in list(TYPICAL_SENTENCES.values()) + ["无关内容", ""]:
        result = analyze(text)
        payload = json.dumps(result, ensure_ascii=False)
        restored = json.loads(payload)
        assert restored["emotion"] == result["emotion"]
        assert isinstance(restored["timestamp"], str)
        assert "T" in restored["timestamp"]  # ISO 8601
