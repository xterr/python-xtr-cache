"""A pool on a connection nobody registered."""

from __future__ import annotations

from redis.asyncio import Redis
from xtr_dependency_injection import Reference, configure

from xtr_cache.bundle import CacheConfig


@configure
def cache() -> CacheConfig:
    return CacheConfig(app=Reference(Redis, "absent"))
