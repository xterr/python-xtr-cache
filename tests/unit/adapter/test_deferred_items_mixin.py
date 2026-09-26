"""The deferred queue behind every pool that batches its writes."""

from __future__ import annotations

import pytest

from tests.support.scripted_adapter import ScriptedAdapter
from xtr_cache import ArrayAdapter, CacheItem, TagAwareAdapter
from xtr_cache.adapter.deferred_items_mixin import DeferredItemsMixin

pytestmark = pytest.mark.anyio


def test_the_pools_that_batch_writes_share_it() -> None:
    assert isinstance(ArrayAdapter(), DeferredItemsMixin)
    assert isinstance(TagAwareAdapter(ArrayAdapter()), DeferredItemsMixin)


async def test_a_save_is_a_deferred_save_committed_at_once() -> None:
    pool = ScriptedAdapter()

    assert await pool.save(CacheItem("a", 1))

    assert [operation for operation, _ in pool.calls] == ["save"]


async def test_queued_items_are_committed_by_a_reset_and_only_then() -> None:
    pool = ScriptedAdapter()
    assert await pool.save_deferred(CacheItem("a", 1))
    assert pool.calls == []

    await pool.reset()
    await pool.reset()

    assert [operation for operation, _ in pool.calls] == ["save"]


async def test_a_deleted_key_is_no_longer_queued() -> None:
    pool = ScriptedAdapter()
    _ = await pool.save_deferred(CacheItem("a", 1))

    assert await pool.delete_item("a")
    assert await pool.commit()

    assert "a" not in pool.stored


async def test_a_sub_namespace_view_starts_with_nothing_queued() -> None:
    pool = ScriptedAdapter("ns")
    _ = await pool.save_deferred(CacheItem("a", 1))

    view = pool.with_sub_namespace("tenant")
    await view.reset()

    assert pool.stored == {}
    await pool.reset()
    assert "ns:a" in pool.stored
