"""依赖注入容器"""

from app.config import settings
from app.plugins.registry import llm_provider_registry, data_provider_registry


def get_llm_provider():
    """获取当前 LLM 提供者"""
    provider_name = settings.llm_provider
    if not llm_provider_registry.is_registered(provider_name):
        provider_name = "mock"
    return llm_provider_registry.get(provider_name)


def get_data_provider():
    """获取当前数据源提供者"""
    provider_name = settings.data_provider
    if not data_provider_registry.is_registered(provider_name):
        provider_name = "mock"
    return data_provider_registry.get(provider_name)
