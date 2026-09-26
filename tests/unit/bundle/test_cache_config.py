from __future__ import annotations

from typing import cast

import pytest
from redis.asyncio import Redis
from xtr_dependency_injection import Reference

from xtr_cache import InvalidArgumentError
from xtr_cache.bundle import APP_POOL, CacheConfig, PoolConfig


def _mistyped(value: object) -> str:
    """Hand ``value`` over where a string is expected: the mistake under test."""
    return cast("str", value)


def test_with_no_arguments_there_is_one_pool_on_files_under_the_share_dir_with_file_locks() -> None:
    config = CacheConfig()

    assert config.pool_configs() == {APP_POOL: PoolConfig(adapter=("filesystem",))}
    assert config.stampede_lock == "flock://%kernel.share_dir%/cache/locks"
    assert config.directory == "%kernel.share_dir%/cache"
    assert config.prefix_seed == "%kernel.project_dir%"


def test_every_pool_is_normalised_and_a_pool_without_adapter_takes_the_apps() -> None:
    reference = Reference(Redis, "cache")
    config = CacheConfig(
        app=["array", "filesystem"],
        pools={
            "one": "array",
            "many": ["array", reference],
            "inherits": PoolConfig(default_lifetime=5, tags=True, namespace="ns"),
        },
    )

    assert config.pool_configs() == {
        "app": PoolConfig(adapter=("array", "filesystem")),
        "one": PoolConfig(adapter=("array",)),
        "many": PoolConfig(adapter=("array", reference)),
        "inherits": PoolConfig(
            adapter=("array", "filesystem"),
            default_lifetime=5,
            tags=True,
            namespace="ns",
        ),
    }


def test_a_pool_named_app_is_refused() -> None:
    with pytest.raises(InvalidArgumentError, match='set it with the "app" option'):
        _ = CacheConfig(pools={"app": "array"})


def test_a_pool_without_a_name_is_refused() -> None:
    with pytest.raises(InvalidArgumentError, match="non-empty name"):
        _ = CacheConfig(pools={"": "array"})


def test_an_adapter_of_the_wrong_type_is_refused() -> None:
    with pytest.raises(InvalidArgumentError, match="string or a Reference"):
        _ = CacheConfig(pools={"bad": [_mistyped(1)]})
    with pytest.raises(InvalidArgumentError, match="string or a Reference"):
        _ = CacheConfig(app=_mistyped(3))


def test_a_pool_may_keep_its_tags_in_another_pool_but_not_in_itself_or_nowhere() -> None:
    config = CacheConfig(pools={"items": PoolConfig(tags="app"), "tags": "array"})

    assert config.pool_configs()["items"].tags == "app"
    with pytest.raises(InvalidArgumentError, match='keeps its tags in "items"'):
        _ = CacheConfig(pools={"items": PoolConfig(tags="items")})
    with pytest.raises(InvalidArgumentError, match='keeps its tags in "nope"'):
        _ = CacheConfig(pools={"items": PoolConfig(tags="nope")})
