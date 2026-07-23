"""插件包初始化 - 启动时自动发现注册所有插件"""

import logging
import os
from pathlib import Path

from app.plugins.registry import (
    data_provider_registry,
    llm_provider_registry,
    agent_registry,
    fee_model_registry,
    slippage_model_registry,
    rule_registry,
    auto_discover_plugins,
)

logger = logging.getLogger(__name__)


def init_all_plugins():
    """初始化所有插件 - 在应用启动时调用"""
    app_root = Path(__file__).resolve().parent.parent  # backend/app

    plugin_dirs = [
        (app_root / "plugins" / "data_providers", "app.plugins.data_providers"),
        (app_root / "plugins" / "llm_providers", "app.plugins.llm_providers"),
        (app_root / "plugins" / "fee_models", "app.plugins.fee_models"),
        (app_root / "plugins" / "slippage_models", "app.plugins.slippage_models"),
        (app_root / "risk" / "rules", "app.risk.rules"),
        (app_root / "agents", "app.agents"),
    ]

    for package_dir, package_name in plugin_dirs:
        try:
            auto_discover_plugins(str(package_dir), package_name)
        except Exception as e:
            logger.warning("插件发现失败 %s: %s", package_name, e)

    logger.info(
        "插件已加载: data=%s llm=%s agents=%s fee=%s slip=%s rules=%s",
        data_provider_registry.list_available(),
        llm_provider_registry.list_available(),
        agent_registry.list_available(),
        fee_model_registry.list_available(),
        slippage_model_registry.list_available(),
        rule_registry.list_available(),
    )
