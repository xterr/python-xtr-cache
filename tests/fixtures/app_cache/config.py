"""One pool per kind of adapter the bundle can build; nothing reaches a server."""

from __future__ import annotations

from xtr_dependency_injection import configure, env

from xtr_cache.bundle import CacheConfig, PoolConfig

REDIS_DSN = "redis://localhost:6379/15"
"""A DSN the pool builds a client for, which connects only if a value is read — and none is."""


@configure
def cache() -> CacheConfig:
    return CacheConfig(
        app="array",
        pools={
            "files": "filesystem",
            "other_files": "filesystem",
            "chained": ["array", "filesystem"],
            "tagged": PoolConfig(adapter="array", tags=True),
            "tagged_chain": PoolConfig(adapter=["array", "array"], tags="versions"),
            "versions": "array",
            "inherits": PoolConfig(default_lifetime=5),
            "shared": PoolConfig(adapter="filesystem", namespace="shared"),
            "from_env": env("CACHE_TEST_DSN"),
            "redis": REDIS_DSN,
        },
        directory=env("CACHE_TEST_DIR"),
        prefix_seed="seed",
        stampede_lock="in-memory",
    )
