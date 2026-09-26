"""Pools encrypted with a key read from the environment."""

from __future__ import annotations

from typing import Annotated

from xtr_dependency_injection import Autowire, as_service, configure, env

from xtr_cache.bundle import CacheConfig
from xtr_cache.marshaller import MarshallerInterface, SodiumMarshaller


@configure
def cache() -> CacheConfig:
    return CacheConfig(directory=env("CACHE_TEST_DIR"), stampede_lock=None)


@as_service
def marshaller(key: Annotated[str, Autowire(env="CACHE_DECRYPTION_KEY")]) -> MarshallerInterface:
    return SodiumMarshaller([key])
