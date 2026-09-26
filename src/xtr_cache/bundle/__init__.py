"""The xtr-dependency-injection bundle for xtr-cache."""

from __future__ import annotations

from .cache_bundle import CACHE_CHANNEL, CacheBundle
from .cache_config import APP_POOL, CacheConfig, PoolEntry
from .pool_config import AdapterEntry, PoolConfig

__all__ = [
    "APP_POOL",
    "CACHE_CHANNEL",
    "AdapterEntry",
    "CacheBundle",
    "CacheConfig",
    "PoolConfig",
    "PoolEntry",
]
