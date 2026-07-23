"""Agent 插件抽象基类与输入/输出模型"""

from abc import ABC, abstractmethod
from pydantic import BaseModel
from typing import Any

class AgentInput(BaseModel):
    request_id: str
    user_id: str
    context: dict[str, Any] = {}

class AgentOutput(BaseModel):
    agent_name: str
    status: str  # success/failed/insufficient/blocked
    data: dict[str, Any] = {}
    error: str | None = None
    trace: dict[str, Any] = {}

class AgentPlugin(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...
    
    @property
    @abstractmethod
    def capabilities(self) -> list[str]: ...
    
    @abstractmethod
    async def execute(self, input: AgentInput) -> AgentOutput: ...
    
    @abstractmethod
    async def health_check(self) -> dict: ...
