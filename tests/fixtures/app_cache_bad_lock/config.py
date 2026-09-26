"""A stampede lock on a DSN no lock store serves."""

from __future__ import annotations

from xtr_dependency_injection import configure

from xtr_cache.bundle import CacheConfig


@configure
def cache() -> CacheConfig:
    return CacheConfig(app="array", stampede_lock="bogus://x")
