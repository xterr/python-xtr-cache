from __future__ import annotations

import pytest

from xtr_cache import (
    AdapterInterface,
    ArrayAdapter,
    CacheInterface,
    CacheItemPoolInterface,
    ChainAdapter,
    NullAdapter,
    TagAwareAdapter,
)


@pytest.mark.parametrize(
    "pool",
    [ArrayAdapter(), NullAdapter(), ChainAdapter([NullAdapter()]), TagAwareAdapter(NullAdapter())],
)
def test_every_adapter_is_a_pool_and_a_cache(pool: object) -> None:
    assert isinstance(pool, AdapterInterface)
    assert isinstance(pool, CacheItemPoolInterface)
    assert isinstance(pool, CacheInterface)


def test_an_unrelated_object_is_not() -> None:
    assert not isinstance(object(), AdapterInterface)
