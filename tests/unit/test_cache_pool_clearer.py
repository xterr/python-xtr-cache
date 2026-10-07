from __future__ import annotations

import pytest

from xtr_cache import (
    ArrayAdapter,
    CacheItemPoolInterface,
    CachePoolClearer,
    InvalidArgumentError,
    NullAdapter,
    TagAwareAdapter,
)
from xtr_cache.cache_pool_clearer import PoolCapabilities

pytestmark = pytest.mark.anyio


async def test_pools_are_known_by_name_and_listed_sorted() -> None:
    clearer = CachePoolClearer({"b": ArrayAdapter(), "a": ArrayAdapter()})

    assert clearer.pool_names() == ("a", "b")
    assert clearer.has_pool("a")
    assert not clearer.has_pool("c")
    assert repr(clearer) == "CachePoolClearer(['a', 'b'])"


async def test_a_pool_given_as_a_function_is_built_once_when_first_asked_for() -> None:
    built: list[ArrayAdapter] = []

    async def build() -> CacheItemPoolInterface:
        built.append(ArrayAdapter())
        return built[-1]

    clearer = CachePoolClearer({"lazy": build})

    assert not built
    first = await clearer.get_pool("lazy")
    assert await clearer.get_pool("lazy") is first
    assert len(built) == 1


async def test_clearing_by_name_or_all_at_once() -> None:
    a, b = ArrayAdapter(), ArrayAdapter()
    clearer = CachePoolClearer({"a": a, "b": b})
    for pool in (a, b):
        _ = await pool.save((await pool.get_item("user.1")).set(1))
        _ = await pool.save((await pool.get_item("order.1")).set(1))

    assert await clearer.clear_pool("a", "user.")
    assert not await a.has_item("user.1")
    assert await a.has_item("order.1")

    assert await clearer.clear()
    assert not await b.has_item("order.1")


async def test_an_unknown_pool_is_refused() -> None:
    with pytest.raises(InvalidArgumentError, match=r'Cache pool "nope" not found\.'):
        _ = await CachePoolClearer().get_pool("nope")


def test_capability_of_a_built_pool_is_read_from_its_type() -> None:
    clearer = CachePoolClearer(
        {"memory": ArrayAdapter(), "null": NullAdapter(), "tagged": TagAwareAdapter(NullAdapter())},
    )

    assert clearer.is_prunable("memory")
    assert not clearer.is_prunable("null")
    assert clearer.is_tag_aware("tagged")
    assert not clearer.is_tag_aware("memory")


async def test_capability_of_a_lazy_pool_is_answered_without_building_it() -> None:
    async def never() -> CacheItemPoolInterface:
        raise AssertionError  # building would reach a server

    clearer = CachePoolClearer(
        {"redis": never, "sessions": never},
        capabilities={
            "redis": PoolCapabilities(tag_aware=False, prunable=False),
            "sessions": PoolCapabilities(tag_aware=True, prunable=True),
        },
    )

    assert not clearer.is_prunable("redis")
    assert not clearer.is_tag_aware("redis")
    assert clearer.is_prunable("sessions")
    assert clearer.is_tag_aware("sessions")
