"""Enable the real DeepSeek text provider for local development.

Upserts the single text-capability AIModelConfig row to provider=deepseek so the
onboarding interview runs the real, profile-driven questioning instead of the
deterministic mock. Requires APP_ENV=development and a configured
DEEPSEEK_API_KEY (the browser never receives the credential).

Usage: cd backend && .venv/bin/python scripts/seed_dev_ai_config.py
"""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import async_session_factory
from app.models.ai_config import AIModelConfig

DEEPSEEK_MODEL = "deepseek-v4-flash"


async def seed_dev_ai_config(
    session: AsyncSession,
    *,
    app_env: str,
    model_name: str = DEEPSEEK_MODEL,
) -> AIModelConfig:
    if app_env != "development":
        raise RuntimeError("Development AI config seeding requires APP_ENV=development")
    if settings.deepseek_api_key is None or not settings.deepseek_api_key.get_secret_value().strip():
        raise ValueError("DEEPSEEK_API_KEY must be configured before enabling the deepseek provider")

    config = await session.scalar(
        select(AIModelConfig).where(AIModelConfig.capability == "text")
    )
    if config is None:
        config = AIModelConfig(
            capability="text",
            provider="deepseek",
            model_name=model_name,
            api_key_ref="DEEPSEEK_API_KEY",
            prompt_version="v1",
            enabled=True,
            version=1,
        )
        session.add(config)
    else:
        config.provider = "deepseek"
        config.model_name = model_name
        config.api_key_ref = "DEEPSEEK_API_KEY"
        config.enabled = True
        config.version += 1
    await session.flush()
    return config


async def _run() -> None:
    async with async_session_factory() as session:
        config = await seed_dev_ai_config(session, app_env=settings.app_env)
        await session.commit()
        print(
            f"text provider enabled: provider={config.provider} "
            f"model={config.model_name} enabled={config.enabled}"
        )


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
