from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


DEEPSEEK_MODELS = {"deepseek-v4-flash", "deepseek-v4-pro"}


def validate_provider_model(capability: "AICapability", provider: str, model_name: str) -> None:
    if capability == AICapability.TEXT:
        if provider not in {"mock", "deepseek"}:
            raise ValueError("Unsupported text provider")
        if provider == "deepseek" and model_name not in DEEPSEEK_MODELS:
            raise ValueError("Unsupported DeepSeek model")
        return
    expected_model = (
        "web-speech-recognition"
        if capability == AICapability.STT
        else "web-speech-synthesis"
    )
    if provider != "browser" or model_name != expected_model:
        raise ValueError(f"{capability.value} requires the browser provider and model")


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
        validate_provider_model(self.capability, self.provider, self.model_name)
        if self.provider == "deepseek" and self.api_key_ref not in {
            None,
            "DEEPSEEK_API_KEY",
        }:
            raise ValueError("DeepSeek uses the DEEPSEEK_API_KEY reference")
        return self


class AIConnectionTest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability: AICapability
    provider: str = Field(min_length=1, max_length=64)
    model_name: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_provider(self):
        validate_provider_model(self.capability, self.provider, self.model_name)
        return self


class AISettingsResponse(BaseModel):
    id: str | None
    capability: AICapability
    provider: str
    model_name: str
    base_url: str | None
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
