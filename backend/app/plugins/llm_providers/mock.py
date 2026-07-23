"""Mock LLM 提供者 - 返回预置的 JSON 风格响应，用于测试"""

import json

from pydantic import BaseModel

from app.plugins.llm_providers.base import LLMProvider, LLMRequest, LLMResponse


class MockLLMProvider(LLMProvider):
    """返回固定占位响应的 Mock LLM，便于无外部依赖地测试链路连通性"""

    async def complete(self, request: LLMRequest) -> LLMResponse:
        content = self._canned_response(request)
        return LLMResponse(
            content=content,
            model="mock-llm",
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )

    async def complete_structured(self, request: LLMRequest, schema: type[BaseModel]) -> BaseModel:
        content = self._canned_response(request)
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            data = {}
        try:
            return schema.model_validate(data)
        except Exception:
            return schema.model_validate({})

    @staticmethod
    def _canned_response(request: LLMRequest) -> str:
        payload = {
            "analysis": "这是来自 Mock LLM 的占位分析。",
            "summary": request.user_message[:200],
            "recommendation": "hold",
            "confidence": 0.5,
            "reasoning": "Mock LLM 不执行真实推理，仅用于测试链路连通性。",
        }
        return json.dumps(payload, ensure_ascii=False)


def register():
    from app.plugins.registry import llm_provider_registry
    llm_provider_registry.register("mock", MockLLMProvider)
