"""Authenticated StepFun Realtime WebSocket proxy."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator
from sqlalchemy import select
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from app.ai_catalog import (
    STEPFUN_REALTIME_MODEL,
    STEPFUN_REALTIME_URL,
    STEPFUN_REALTIME_VOICE,
)
from app.config import settings
from app.core.security import resolve_active_user
from app.db.session import create_db_session
from app.models.ai_config import AIModelConfig
from app.models.onboarding import OnboardingSession, ProfileMessage

router = APIRouter()
logger = logging.getLogger(__name__)

AUTH_TIMEOUT_SECONDS = 8
SESSION_WARNING_SECONDS = 28 * 60
SESSION_LIMIT_SECONDS = 30 * 60
CLIENT_EVENT_TYPES = {"audio.append", "response.cancel", "session.close"}


class VoiceAuth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    token: str
    surface: str
    session_id: str | None = None
    context_version: str | None = None

    @field_validator("type")
    @classmethod
    def auth_type(cls, value: str) -> str:
        if value != "auth":
            raise ValueError("first event must be auth")
        return value

    @field_validator("surface")
    @classmethod
    def supported_surface(cls, value: str) -> str:
        if value not in {"onboarding", "desk"}:
            raise ValueError("unsupported voice surface")
        return value


def session_instructions(surface: str) -> str:
    common = (
        "你是 Finance God 的实时语音助手。使用简洁自然的中文交流。"
        "不得声称已执行未通过服务端确认的动作，不得承诺收益或本金安全。"
        "涉及实时行情、账户、持仓、研究结论或交易动作时，必须明确以页面服务端事实为准。"
    )
    if surface == "onboarding":
        return common + "当前处于投资画像访谈，一次只问一个生活化问题；敏感问题必须说明可以跳过。"
    return common + "当前处于交易台。一般金融教育可以直接回答，但不得编造实时市场或账户数据。"


def session_update(surface: str) -> dict[str, Any]:
    return {
        "type": "session.update",
        "session": {
            "modalities": ["text", "audio"],
            "instructions": session_instructions(surface),
            "voice": STEPFUN_REALTIME_VOICE,
            "input_audio_format": "pcm16",
            "output_audio_format": "pcm16",
            "turn_detection": {
                "type": "server_vad",
                "prefix_padding_ms": 500,
                "silence_duration_ms": 500,
                "energy_awakeness_threshold": 2500,
            },
        },
    }


def map_upstream_event(event: dict[str, Any]) -> dict[str, Any] | None:
    mappings = {
        "input_audio_buffer.speech_started": "speech.started",
        "input_audio_buffer.speech_stopped": "speech.stopped",
        "conversation.item.input_audio_transcription.delta": "transcript.user.delta",
        "conversation.item.input_audio_transcription.completed": "transcript.user.done",
        "response.audio_transcript.delta": "transcript.assistant.delta",
        "response.audio_transcript.done": "transcript.assistant.done",
        "response.audio.delta": "audio.delta",
        "response.audio.done": "audio.done",
    }
    event_type = str(event.get("type"))
    mapped = mappings.get(event_type)
    if mapped:
        value = event.get("delta")
        if value is None:
            value = event.get("transcript", "")
        return {"type": mapped, "data": value}
    if event_type == "error":
        error = event.get("error") if isinstance(event.get("error"), dict) else {}
        return {
            "type": "session.error",
            "code": str(error.get("code") or "upstream_error"),
            "message": "实时语音服务返回错误，请改用文字输入。",
        }
    return None


async def authorize(auth: VoiceAuth):
    async with create_db_session() as db:
        user = await resolve_active_user(auth.token, db)
        if user is None:
            return None
        config = await db.scalar(
            select(AIModelConfig).where(
                AIModelConfig.capability == "realtime",
                AIModelConfig.enabled.is_(True),
            )
        )
        if config is not None and (
            config.provider != "stepfun" or config.model_name != STEPFUN_REALTIME_MODEL
        ):
            return None
        if auth.surface == "onboarding":
            if not auth.session_id:
                return None
            owned = await db.scalar(
                select(OnboardingSession.id).where(
                    OnboardingSession.id == auth.session_id,
                    OnboardingSession.user_id == user.id,
                    OnboardingSession.status.in_(("active", "ready")),
                )
            )
            if owned is None:
                return None
        elif not auth.context_version or not auth.context_version.startswith(f"desk:{user.id}:"):
            return None
        return user


async def client_to_upstream(websocket: WebSocket, upstream) -> None:
    while True:
        event = json.loads(await websocket.receive_text())
        event_type = event.get("type")
        if event_type not in CLIENT_EVENT_TYPES:
            await websocket.send_json(
                {"type": "session.error", "code": "unsupported_event", "message": "不支持的语音事件。"}
            )
            continue
        if event_type == "audio.append":
            audio = event.get("audio")
            if isinstance(audio, str) and audio:
                await upstream.send(json.dumps({"type": "input_audio_buffer.append", "audio": audio}))
        elif event_type == "response.cancel":
            await upstream.send(json.dumps({"type": "response.cancel"}))
        else:
            return


async def persist_final_transcript(
    *,
    auth: VoiceAuth,
    role: str,
    content: str,
) -> None:
    """Persist final text only. Raw audio and incremental transcript never enter storage."""
    normalized = content.strip()[:4000]
    if auth.surface != "onboarding" or not auth.session_id or not normalized:
        return
    async with create_db_session() as db:
        session = await db.get(OnboardingSession, auth.session_id)
        if session is None:
            return
        db.add(
            ProfileMessage(
                session_id=session.id,
                role=role,
                content=normalized,
                input_mode="voice",
                target_dimension=session.current_dimension,
                sensitive=session.current_dimension == "income_stability",
            )
        )
        await db.commit()


async def upstream_to_client(websocket: WebSocket, upstream, auth: VoiceAuth) -> None:
    async for raw in upstream:
        mapped = map_upstream_event(json.loads(raw))
        if mapped is not None:
            if mapped["type"] == "transcript.user.done":
                await persist_final_transcript(auth=auth, role="user", content=str(mapped.get("data") or ""))
            elif mapped["type"] == "transcript.assistant.done":
                await persist_final_transcript(auth=auth, role="assistant", content=str(mapped.get("data") or ""))
            await websocket.send_json(mapped)


async def session_clock(websocket: WebSocket) -> None:
    await asyncio.sleep(SESSION_WARNING_SECONDS)
    await websocket.send_json(
        {"type": "session.warning", "message": "本次语音通话将在两分钟后结束。"}
    )
    await asyncio.sleep(SESSION_LIMIT_SECONDS - SESSION_WARNING_SECONDS)
    await websocket.send_json(
        {"type": "session.closed", "reason": "time_limit", "message": "语音通话已达到 30 分钟上限。"}
    )


@router.websocket("/realtime")
async def realtime_voice(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), AUTH_TIMEOUT_SECONDS)
        auth = VoiceAuth.model_validate_json(raw)
    except (asyncio.TimeoutError, ValidationError, ValueError, WebSocketDisconnect):
        await websocket.send_json(
            {"type": "session.error", "code": "authentication_failed", "message": "语音会话认证失败。"}
        )
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    user = await authorize(auth)
    if user is None:
        await websocket.send_json(
            {"type": "session.error", "code": "forbidden", "message": "无权访问该语音上下文。"}
        )
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    if settings.stepfun_api_key is None:
        await websocket.send_json(
            {"type": "session.error", "code": "not_configured", "message": "实时语音模型尚未配置。"}
        )
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        return

    key = settings.stepfun_api_key.get_secret_value()
    try:
        async with connect(
            f"{STEPFUN_REALTIME_URL}?model={STEPFUN_REALTIME_MODEL}",
            additional_headers={"Authorization": f"Bearer {key}"},
            open_timeout=10,
            close_timeout=5,
            max_size=8 * 1024 * 1024,
            proxy=None,
        ) as upstream:
            await upstream.send(json.dumps(session_update(auth.surface), ensure_ascii=False))
            await websocket.send_json(
                {"type": "session.ready", "model": STEPFUN_REALTIME_MODEL, "voice": STEPFUN_REALTIME_VOICE}
            )
            tasks = {
                asyncio.create_task(client_to_upstream(websocket, upstream)),
                asyncio.create_task(upstream_to_client(websocket, upstream, auth)),
                asyncio.create_task(session_clock(websocket)),
            }
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            for task in done:
                with suppress(WebSocketDisconnect, ConnectionClosed, asyncio.CancelledError):
                    task.result()
    except (OSError, ConnectionClosed) as exc:
        logger.warning("StepFun realtime connection failed for user=%s", user.id, exc_info=exc)
        with suppress(WebSocketDisconnect, RuntimeError):
            await websocket.send_json(
                {"type": "session.error", "code": "upstream_unavailable", "message": "实时语音服务连接中断，请改用文字输入。"}
            )
    finally:
        with suppress(RuntimeError):
            await websocket.close()
