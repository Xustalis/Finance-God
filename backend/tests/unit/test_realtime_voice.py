from app.api.v1.voice import map_upstream_event, session_update
from app.schemas.admin import AIConnectionTest, AISettingsUpdate


def test_realtime_admin_contract_accepts_only_controlled_stepfun_model() -> None:
    setting = AISettingsUpdate(
        capability="realtime",
        provider="stepfun",
        model_name="stepaudio-2.5-realtime",
        api_key_ref="STEPFUN_API_KEY",
    )
    probe = AIConnectionTest(
        capability="realtime",
        provider="stepfun",
        model_name="stepaudio-2.5-realtime",
    )

    assert setting.api_key_ref == "STEPFUN_API_KEY"
    assert probe.provider == "stepfun"


def test_realtime_session_is_server_owned_pcm16_with_vad() -> None:
    event = session_update("desk")
    session = event["session"]

    assert session["voice"] == "wenrounansheng"
    assert session["input_audio_format"] == "pcm16"
    assert session["output_audio_format"] == "pcm16"
    assert session["turn_detection"] == {
        "type": "server_vad",
        "prefix_padding_ms": 500,
        "silence_duration_ms": 500,
        "energy_awakeness_threshold": 2500,
    }
    assert "交易动作" in session["instructions"]


def test_upstream_events_are_reduced_to_public_allowlist() -> None:
    assert map_upstream_event(
        {"type": "input_audio_buffer.speech_started"}
    ) == {"type": "speech.started", "data": ""}
    assert map_upstream_event(
        {"type": "response.audio.delta", "delta": "base64-audio"}
    ) == {"type": "audio.delta", "data": "base64-audio"}
    assert map_upstream_event({"type": "session.created", "secret": "hidden"}) is None
    assert map_upstream_event(
        {"type": "error", "error": {"code": "rate_limit", "message": "internal"}}
    ) == {
        "type": "session.error",
        "code": "rate_limit",
        "message": "实时语音服务返回错误，请改用文字输入。",
    }
