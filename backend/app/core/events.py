"""领域事件总线"""

from collections import defaultdict
from typing import Any, Callable

_handlers: dict[str, list[Callable]] = defaultdict(list)


def subscribe(event_type: str, handler: Callable):
    """订阅事件"""
    _handlers[event_type].append(handler)


def publish(event_type: str, payload: Any = None):
    """发布事件（同步执行，简单实现）"""
    for handler in _handlers.get(event_type, []):
        handler(payload)


async def publish_async(event_type: str, payload: Any = None):
    """发布事件（异步执行）"""
    for handler in _handlers.get(event_type, []):
        result = handler(payload)
        if hasattr(result, "__await__"):
            await result
