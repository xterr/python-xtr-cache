"""A pool on a DSN no adapter serves, with credentials the error must not echo."""

from __future__ import annotations

from xtr_dependency_injection import configure

from xtr_cache.bundle import CacheConfig


@configure
def cache() -> CacheConfig:
    return CacheConfig(app="array", pools={"reports": "mysql://user:secret@db/app"})
