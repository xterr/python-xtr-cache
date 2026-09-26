from __future__ import annotations

import pytest

from tests.support.callbacks import Computation
from xtr_cache import (
    AdapterInterface,
    CacheItem,
    InvalidArgumentError,
    NamespacedPoolInterface,
    NullAdapter,
)

pytestmark = pytest.mark.anyio


async def test_every_read_misses_and_every_write_succeeds() -> None:
    pool = NullAdapter()
    item = (await pool.get_item("a")).set(1)

    assert await pool.save(item)
    assert await pool.save_deferred(item)
    assert await pool.commit()
    assert not (await pool.get_item("a")).is_hit()
    assert not await pool.has_item("a")
    assert [i.is_hit() for i in (await pool.get_items(["a", "b"])).values()] == [False, False]
    assert await pool.delete_item("a")
    assert await pool.delete_items(["a"])
    assert await pool.delete("a")
    assert await pool.clear()
    await pool.reset()


async def test_the_cache_computes_every_time() -> None:
    pool = NullAdapter()
    compute = Computation(1)

    assert await pool.get("a", compute) == 1
    assert await pool.get("a", compute) == 1
    assert compute.calls == 2


async def test_bad_keys_and_a_negative_beta_are_still_refused() -> None:
    pool = NullAdapter()
    compute = Computation(1)

    with pytest.raises(InvalidArgumentError):
        _ = await pool.get("a:b", compute)
    with pytest.raises(InvalidArgumentError):
        _ = await pool.get("a", compute, beta=-1)
    with pytest.raises(InvalidArgumentError):
        _ = await pool.delete_items(["a:b"])
    with pytest.raises(InvalidArgumentError):
        _ = await pool.has_item("")


def test_a_sub_namespace_is_the_same_pool() -> None:
    pool = NullAdapter()

    assert pool.with_sub_namespace("tenant") is pool
    assert isinstance(pool, AdapterInterface)
    assert isinstance(pool, NamespacedPoolInterface)
    assert repr(pool) == "NullAdapter()"


async def test_its_items_are_plain_cache_items() -> None:
    assert isinstance(await NullAdapter().get_item("a"), CacheItem)
