"""The application pool on a Redis client the application registers itself."""

from __future__ import annotations

from redis.asyncio import Redis
from xtr_dependency_injection import Reference, configure

from xtr_cache.bundle import CacheConfig

from .services import CACHE


@configure
def cache() -> CacheConfig:
    return CacheConfig(app=Reference(Redis, CACHE), stampede_lock=None)
