"""内存缓存 - 替代 Redis (MVP单机)"""

from cachetools import TTLCache
from typing import Any

# 默认 TTL 300s；需要不同 TTL 时使用独立 cache 桶
_DEFAULT_TTL = 300
_cache: TTLCache = TTLCache(maxsize=1000, ttl=_DEFAULT_TTL)
_ttl_caches: dict[int, TTLCache] = {}


def _get_cache(ttl: int | None = None) -> TTLCache:
    if ttl is None or ttl == _DEFAULT_TTL:
        return _cache
    if ttl not in _ttl_caches:
        _ttl_caches[ttl] = TTLCache(maxsize=500, ttl=ttl)
    return _ttl_caches[ttl]


def cache_get(key: str) -> Any | None:
    # 先查默认桶，再查自定义 TTL 桶
    if key in _cache:
        return _cache[key]
    for c in _ttl_caches.values():
        if key in c:
            return c[key]
    return None


def cache_set(key: str, value: Any, ttl: int | None = None) -> None:
    # 避免同一 key 残留在其他桶
    cache_delete(key)
    _get_cache(ttl)[key] = value


def cache_delete(key: str) -> None:
    _cache.pop(key, None)
    for c in _ttl_caches.values():
        c.pop(key, None)


def cache_clear() -> None:
    _cache.clear()
    for c in _ttl_caches.values():
        c.clear()
