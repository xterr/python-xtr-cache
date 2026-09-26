from __future__ import annotations

import pytest

from xtr_cache import ArrayAdapter, CacheItemPoolInterface, CachePoolClearer, InvalidArgumentError

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
