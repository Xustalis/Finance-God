"""DeepSeek LLM 提供者 - 基于 OpenAI 兼容的 /chat/completions 接口"""

import json

import httpx
from pydantic import BaseModel

from app.config import settings
from app.plugins.llm_providers.base import LLMProvider, LLMRequest, LLMResponse


class DeepSeekLLMProvider(LLMProvider):
    """DeepSeek API 提供者（OpenAI 兼容）"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ):
        self.api_key = api_key or settings.deepseek_api_key
        self.base_url = base_url or settings.deepseek_base_url
        self.model = model or settings.deepseek_model

    async def complete(self, request: LLMRequest) -> LLMResponse:
        payload = self._build_payload(request)
        data = await self._post(payload)
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return LLMResponse(content=content, model=self.model, usage=usage)

    async def complete_structured(self, request: LLMRequest, schema: type[BaseModel]) -> BaseModel:
        req = request.model_copy()
        req.response_format = {"type": "json_object"}
        payload = self._build_payload(req)
        data = await self._post(payload)
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        return schema.model_validate(parsed)

    def _build_payload(self, request: LLMRequest) -> dict:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_message},
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.response_format:
            payload["response_format"] = request.response_format
        return payload

    async def _post(self, payload: dict) -> dict:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            return resp.json()


def register():
    from app.plugins.registry import llm_provider_registry
    llm_provider_registry.register("deepseek", DeepSeekLLMProvider)
