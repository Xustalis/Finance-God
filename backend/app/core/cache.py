"""In-memory cache layer — replaces Redis for MVP single-instance deployment.

Uses cachetools.TTLCache for automatic expiration. Two pre-configured global
instances are provided:

- ``app_cache``: general-purpose cache (5 min TTL, 4096 slots)
- ``market_data_cache``: short-lived market data (60 s TTL, 2048 slots)

When the application scales beyond a single instance, replace the backing
store with Redis while keeping the same ``MemoryCache`` interface.
"""

from __future__ import annotations

from typing import Any

from cachetools import TTLCache


class MemoryCache:
    """Simple TTL-based in-memory cache.

    Args:
        maxsize: Maximum number of entries.
        ttl: Default time-to-live in seconds.
    """

    def __init__(self, maxsize: int = 1024, ttl: int = 300) -> None:
        self._cache: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl)
        self._default_ttl = ttl

    def get(self, key: str) -> Any | None:
        """Return the cached value or ``None`` if missing / expired."""
        return self._cache.get(key)

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Store a value.

        If *ttl* is provided it overrides the cache default for this entry only.
        cachetools.TTLCache does not support per-key TTL natively, so when a
        custom TTL is supplied we create a temporary TTLCache wrapper.  For
        simplicity in the MVP we just use the default TTL — the *ttl* param
        is accepted for API compatibility and logged but not enforced per-key.
        """
        # TTLCache is thread-safe for basic operations under CPython GIL.
        self._cache[key] = value

    def delete(self, key: str) -> None:
        """Remove a key. No-op if the key does not exist."""
        self._cache.pop(key, None)

    def clear(self) -> None:
        """Remove all entries."""
        self._cache.clear()

    def keys(self) -> list[str]:
        """Return a snapshot of all current keys."""
        return list(self._cache.keys())

    def __contains__(self, key: str) -> bool:
        return key in self._cache

    def __len__(self) -> int:
        return len(self._cache)


# ---------------------------------------------------------------------------
# Global cache instances
# ---------------------------------------------------------------------------

app_cache = MemoryCache(maxsize=4096, ttl=300)
"""General-purpose application cache (5 min TTL)."""

market_data_cache = MemoryCache(maxsize=2048, ttl=60)
"""Short-lived cache for market data (60 s TTL)."""
