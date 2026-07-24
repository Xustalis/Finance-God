"""A deliberately small OpenAI-compatible chat adapter."""

from __future__ import annotations

from typing import Protocol

from openai import OpenAI

from .config import Settings


class ChatClient(Protocol):
    def complete(self, *, system_prompt: str, user_prompt: str) -> str: ...


class OpenAICompatibleChat:
    """Calls one configured OpenAI-compatible model without tool access."""

    def __init__(self, settings: Settings) -> None:
        self._client = OpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
            timeout=60.0,
            max_retries=1,
        )
        self._model = settings.model

    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        response = self._client.responses.create(
            model=self._model,
            instructions=system_prompt,
            input=user_prompt,
        )
        content = response.output_text
        if not content or not content.strip():
            raise RuntimeError("Model returned an empty response")
        return content.strip()
