"""LLM 提供者抽象基类与请求/响应模型"""

from abc import ABC, abstractmethod
from pydantic import BaseModel
from typing import Any

class LLMRequest(BaseModel):
    system_prompt: str
    user_message: str
    temperature: float = 0.7
    max_tokens: int = 4096
    response_format: dict | None = None

class LLMResponse(BaseModel):
    content: str
    model: str
    usage: dict = {}

class LLMProvider(ABC):
    @abstractmethod
    async def complete(self, request: LLMRequest) -> LLMResponse: ...
    
    @abstractmethod
    async def complete_structured(self, request: LLMRequest, schema: type[BaseModel]) -> BaseModel: ...
