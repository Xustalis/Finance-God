"""插件注册中心 - 通用注册/发现/替换机制"""

from typing import TypeVar, Generic, Type
from abc import ABC
import importlib
import logging
import os
import pkgutil

T = TypeVar("T", bound=ABC)
logger = logging.getLogger(__name__)


class PluginRegistry(Generic[T]):
    """通用插件注册中心，支持运行时注册/发现/替换"""

    def __init__(self):
        self._plugins: dict[str, Type[T]] = {}
        self._instances: dict[str, T] = {}

    def register(self, name: str, plugin_class: Type[T]) -> None:
        self._plugins[name] = plugin_class
        # 清除缓存的实例
        self._instances.pop(name, None)

    def get(self, name: str, **kwargs) -> T:
        if name not in self._instances:
            if name not in self._plugins:
                raise KeyError(f"插件未注册: {name}")
            self._instances[name] = self._plugins[name](**kwargs)
        return self._instances[name]

    def list_available(self) -> list[str]:
        return list(self._plugins.keys())

    def is_registered(self, name: str) -> bool:
        return name in self._plugins


# 全局注册实例
data_provider_registry: PluginRegistry = PluginRegistry()
llm_provider_registry: PluginRegistry = PluginRegistry()
agent_registry: PluginRegistry = PluginRegistry()
fee_model_registry: PluginRegistry = PluginRegistry()
slippage_model_registry: PluginRegistry = PluginRegistry()
rule_registry: PluginRegistry = PluginRegistry()


def auto_discover_plugins(package_path: str, package_name: str):
    """自动发现并注册插件

    扫描指定包目录下的所有模块，调用每个模块的 register() 函数（如果存在）。
    package_path 应为包目录本身（如 .../app/agents），而不是其父目录。
    """
    package_dir = package_path if os.path.isdir(package_path) else os.path.dirname(package_path)
    if not os.path.isdir(package_dir):
        logger.warning("插件目录不存在: %s", package_dir)
        return

    for _, module_name, is_pkg in pkgutil.iter_modules([package_dir]):
        # 跳过子包与私有模块
        if is_pkg or module_name.startswith("_") or module_name in {"base", "registry"}:
            continue
        full_name = f"{package_name}.{module_name}"
        try:
            module = importlib.import_module(full_name)
        except Exception as e:
            logger.warning("导入插件模块失败 %s: %s", full_name, e)
            continue
        if hasattr(module, "register"):
            try:
                module.register()
            except Exception as e:
                logger.warning("注册插件失败 %s: %s", full_name, e)
