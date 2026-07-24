import os

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import ApiResponse
from app.core.security import require_admin
from app.db.session import get_db
from app.models.ai_config import AIModelConfig, AdminAuditRecord, PromptVersion
from app.models.user import User
from app.schemas.admin import AICapability, AIConnectionTest, AIConnectionTestResponse, AISettingsResponse, AISettingsUpdate
from app.services.ai_orchestrator import AIAdapterRegistry, ONBOARDING_SYSTEM_PROMPT, get_ai_adapter_registry
from app.config import settings

router = APIRouter()


DEFAULT_CONFIGS = {
    "text": {"provider": "mock", "model_name": "mock-structured-v1"},
    "stt": {"provider": "browser", "model_name": "web-speech-recognition"},
    "tts": {"provider": "browser", "model_name": "web-speech-synthesis"},
}


def safe_config(config: AIModelConfig | None, capability: str) -> dict:
    defaults = DEFAULT_CONFIGS[capability]
    return {
        "id": config.id if config else None,
        "capability": capability,
        "provider": config.provider if config else defaults["provider"],
        "model_name": config.model_name if config else defaults["model_name"],
        "api_key_configured": bool(config and config.api_key_ref and os.getenv(config.api_key_ref)),
        "prompt_version": config.prompt_version if config else "v1",
        "min_rounds": config.min_rounds if config else 6,
        "max_rounds": config.max_rounds if config else 12,
        "enabled": config.enabled if config else True,
        "version": config.version if config else 0,
    }


@router.get("/ai-settings", response_model=ApiResponse[list[AISettingsResponse]])
async def get_ai_settings(
    admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> ApiResponse:
    del admin
    configs = (await db.scalars(select(AIModelConfig))).all()
    by_capability = {config.capability: config for config in configs}
    return ApiResponse.ok(
        [safe_config(by_capability.get(capability), capability) for capability in DEFAULT_CONFIGS]
    )


@router.put("/ai-settings", response_model=ApiResponse[AISettingsResponse])
async def update_ai_settings(
    body: AISettingsUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    registry: AIAdapterRegistry = Depends(get_ai_adapter_registry),
) -> ApiResponse:
    capability = body.capability.value
    if body.enabled and capability == "text":
        if body.provider not in registry.text_providers:
            raise HTTPException(status_code=422, detail="Unsupported text provider")
        if body.provider == "mock" and settings.app_env != "development":
            raise HTTPException(status_code=422, detail="Mock text provider is development-only")
    prompt = None
    if capability == "text":
        prompt = await db.scalar(
            select(PromptVersion).where(PromptVersion.version == body.prompt_version)
        )
        if (
            body.prompt_content
            and body.prompt_version == "v1"
            and prompt is None
            and body.prompt_content != ONBOARDING_SYSTEM_PROMPT
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Built-in Prompt version v1 is immutable",
            )
        if body.prompt_content and prompt is not None and prompt.content != body.prompt_content:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Prompt versions are immutable; choose a new version",
            )
        if not body.prompt_content and prompt is None and body.prompt_version != "v1":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Prompt version must exist before text configuration activation",
            )
    config = await db.scalar(select(AIModelConfig).where(AIModelConfig.capability == capability))
    before = safe_config(config, capability) if config else {}
    if config is None:
        config = AIModelConfig(
            capability=capability,
            provider=body.provider,
            model_name=body.model_name,
            api_key_ref=body.api_key_ref,
            prompt_version=body.prompt_version,
            min_rounds=body.min_rounds,
            max_rounds=body.max_rounds,
            enabled=body.enabled,
            version=1,
            updated_by=admin.id,
        )
        db.add(config)
    else:
        config.provider = body.provider
        config.model_name = body.model_name
        if "api_key_ref" in body.model_fields_set:
            config.api_key_ref = body.api_key_ref
        config.prompt_version = body.prompt_version
        config.min_rounds = body.min_rounds
        config.max_rounds = body.max_rounds
        config.enabled = body.enabled
        config.version += 1
        config.updated_by = admin.id
    await db.flush()
    if capability == "text" and body.prompt_content and prompt is None:
        prompt = PromptVersion(
            version=body.prompt_version,
            content=body.prompt_content,
            active=True,
            created_by=admin.id,
        )
        db.add(prompt)
        await db.flush()
        db.add(
            AdminAuditRecord(
                actor_id=admin.id,
                action="prompt_version.create",
                resource_type="prompt_version",
                resource_id=prompt.id,
                before_data={},
                after_data={"version": prompt.version, "active": prompt.active},
            )
        )
    after = safe_config(config, capability)
    db.add(
        AdminAuditRecord(
            actor_id=admin.id,
            action="ai_settings.update",
            resource_type="ai_model_config",
            resource_id=config.id,
            before_data=before,
            after_data=after,
        )
    )
    await db.flush()
    return ApiResponse.ok(after)


@router.post("/ai-settings/test", response_model=ApiResponse[AIConnectionTestResponse])
async def test_ai_settings(
    body: AIConnectionTest,
    admin: User = Depends(require_admin),
    registry: AIAdapterRegistry = Depends(get_ai_adapter_registry),
) -> ApiResponse:
    del admin
    try:
        probe = await registry.probe(
            capability=body.capability.value,
            provider=body.provider,
            model_name=body.model_name,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Provider connection could not be verified without a configured adapter",
        ) from exc
    return ApiResponse.ok(
        {
            "ok": probe["ok"],
            "capability": body.capability.value,
            "provider": body.provider,
            "model_name": body.model_name,
            "adapter": probe["adapter"],
            "credential_status": "not_required",
        }
    )
