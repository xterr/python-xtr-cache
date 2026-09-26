from __future__ import annotations

from typing import cast

import pytest

from xtr_cache import InvalidArgumentError
from xtr_cache.bundle import PoolConfig


def _mistyped(value: object) -> str:
    """Hand ``value`` over where a string is expected: the mistake under test."""
    return cast("str", value)


def test_with_no_arguments_it_takes_the_apps_adapter_and_keeps_values_forever() -> None:
    pool = PoolConfig()

    assert pool.adapters() == ()
    assert pool.default_lifetime == 0
    assert not pool.tags
    assert pool.namespace is None


def test_one_adapter_or_several_become_a_tuple() -> None:
    assert PoolConfig(adapter="array").adapters() == ("array",)
    assert PoolConfig(adapter=["array", "filesystem"]).adapters() == ("array", "filesystem")


def test_a_pool_that_cannot_be_built_is_refused() -> None:
    with pytest.raises(InvalidArgumentError, match="must not be negative"):
        _ = PoolConfig(default_lifetime=-1)
    with pytest.raises(InvalidArgumentError, match="reserved characters"):
        _ = PoolConfig(namespace="a:b")
    with pytest.raises(InvalidArgumentError, match="string or a Reference"):
        _ = PoolConfig(adapter=[_mistyped(None)])
