from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AICapability(StrEnum):
    TEXT = "text"
    STT = "stt"
    TTS = "tts"


class AISettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability: AICapability
    provider: str = Field(min_length=1, max_length=64)
    model_name: str = Field(min_length=1, max_length=100)
    api_key_ref: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$")
    prompt_version: str = Field(default="v1", min_length=1, max_length=32)
    prompt_content: str | None = Field(default=None, min_length=20, max_length=12000)
    min_rounds: int = Field(default=6, ge=6, le=12)
    max_rounds: int = Field(default=12, ge=6, le=12)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_round_order(self):
        if self.min_rounds > self.max_rounds:
            raise ValueError("min_rounds cannot exceed max_rounds")
        return self


class AIConnectionTest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability: AICapability
    provider: str = Field(min_length=1, max_length=64)
    model_name: str = Field(min_length=1, max_length=100)


class AISettingsResponse(BaseModel):
    id: str | None
    capability: AICapability
    provider: str
    model_name: str
    api_key_configured: bool
    prompt_version: str
    min_rounds: int
    max_rounds: int
    enabled: bool
    version: int


class AIConnectionTestResponse(BaseModel):
    ok: bool
    capability: AICapability
    provider: str
    model_name: str
    adapter: str
    credential_status: str
