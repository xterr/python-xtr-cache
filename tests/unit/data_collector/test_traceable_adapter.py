"""Unit tests for :class:`xtr_cache.data_collector.TraceableAdapter`."""

from __future__ import annotations

from typing import cast

import anyio
import pytest
from xtr_clock import MockClock
from xtr_http_kernel.data_collector import RequestTrace

from tests.support.callbacks import Computation
from xtr_cache import (
    AdapterInterface,
    ArrayAdapter,
    LogicError,
    NamespacedPoolInterface,
    NullAdapter,
    PruneableInterface,
)
from xtr_cache.data_collector import CacheCall, TraceableAdapter

pytestmark = pytest.mark.anyio


def _traced(
    pool: AdapterInterface | None = None, clock: MockClock | None = None
) -> tuple[TraceableAdapter, RequestTrace[CacheCall]]:
    trace: RequestTrace[CacheCall] = RequestTrace("test_cache_calls")
    trace.begin()
    return TraceableAdapter(pool or ArrayAdapter(), "app", trace, clock or MockClock()), trace


async def test_a_missing_item_then_a_found_one_are_recorded_as_a_miss_then_a_hit() -> None:
    cache, trace = _traced()

    item = await cache.get_item("greeting")
    _ = await cache.save(item.set("hello"))
    _ = await cache.get_item("greeting")

    assert [(call.method, call.hits, call.misses) for call in trace.entries()] == [
        ("get_item", 0, 1),
        ("save", 0, 0),
        ("get_item", 1, 0),
    ]


async def test_reading_several_keys_counts_each_hit_and_miss_in_the_order_asked() -> None:
    cache, trace = _traced()
    _ = await cache.save((await cache.get_item("b")).set(2))

    items = await cache.get_items(key for key in ("a", "b"))

    assert list(items) == ["a", "b"]
    assert trace.entries()[-1] == CacheCall("app", "get_items", ("a", "b"), 1, 1, 0.0, None)


async def test_asking_whether_a_key_is_held_counts_as_a_read() -> None:
    cache, trace = _traced()

    assert not await cache.has_item("absent")

    assert trace.entries() == (CacheCall("app", "has_item", ("absent",), 0, 1, 0.0, None),)


async def test_a_value_computed_on_a_get_is_a_miss_timed_by_the_clock() -> None:
    clock = MockClock()
    cache, trace = _traced(clock=clock)

    value = await cache.get("invoice.7", Computation("total", took=0.25, clock=clock))

    assert value == "total"
    assert trace.entries() == (CacheCall("app", "get", ("invoice.7",), 0, 1, 250.0, None),)


async def test_a_value_found_on_a_get_is_a_hit_and_the_callback_never_runs() -> None:
    cache, trace = _traced()
    _ = await cache.get("invoice.7", Computation("total"))
    computation = Computation("other")

    assert await cache.get("invoice.7", computation) == "total"

    assert computation.calls == 0
    assert (trace.entries()[-1].hits, trace.entries()[-1].misses) == (1, 0)


async def test_a_get_whose_callback_raises_is_still_recorded() -> None:
    cache, trace = _traced()

    with pytest.raises(RuntimeError):
        _ = await cache.get("invoice.7", Computation("total", fails_with=RuntimeError("down")))

    assert trace.entries() == (CacheCall("app", "get", ("invoice.7",), 0, 1, 0.0, None),)


async def test_writes_and_deletes_are_recorded_with_what_they_returned() -> None:
    cache, trace = _traced()
    item = (await cache.get_item("a")).set(1)

    _ = await cache.save_deferred(item)
    _ = await cache.commit()
    _ = await cache.delete_item("a")
    _ = await cache.delete_items(key for key in ("b", "c"))
    _ = await cache.delete("d")
    _ = await cache.clear("e")
    _ = await cache.clear()

    assert [(call.method, call.keys, call.result) for call in trace.entries()[1:]] == [
        ("save_deferred", ("a",), True),
        ("commit", (), True),
        ("delete_item", ("a",), True),
        ("delete_items", ("b", "c"), True),
        ("delete", ("d",), True),
        ("clear", ("e",), True),
        ("clear", (), True),
    ]


async def test_reset_reaches_the_pool_and_commits_what_it_deferred() -> None:
    pool = ArrayAdapter()
    cache, trace = _traced(pool)
    _ = await cache.save_deferred((await cache.get_item("a")).set(1))

    await cache.reset()

    assert await pool.has_item("a")
    assert trace.entries()[-1].method == "reset"


async def test_pruning_reaches_a_pool_that_keeps_expired_values() -> None:
    cache, trace = _traced()

    assert await cache.prune()

    assert trace.entries() == (CacheCall("app", "prune", (), 0, 0, 0.0, result=True),)


async def test_pruning_a_pool_that_keeps_nothing_expired_succeeds_and_records_nothing() -> None:
    cache, trace = _traced(NullAdapter())

    assert await cache.prune()

    assert trace.entries() == ()


async def test_a_sub_namespace_view_is_traced_under_the_same_pool_name() -> None:
    pool = ArrayAdapter()
    cache, trace = _traced(pool)

    view = cache.with_sub_namespace("reports")
    _ = await view.get_item("a")

    assert isinstance(view, TraceableAdapter)
    assert view.pool is not pool
    assert trace.entries() == (CacheCall("app", "get_item", ("a",), 0, 1, 0.0, None),)


async def test_a_pool_without_sub_namespaces_cannot_be_given_one() -> None:
    # No adapter of this library lacks sub-namespaces; an application's own pool might.
    cache, _ = _traced(cast("AdapterInterface", object()))

    with pytest.raises(LogicError, match="sub-namespace"):
        _ = cache.with_sub_namespace("reports")


async def test_nothing_is_recorded_outside_a_profiled_request() -> None:
    trace: RequestTrace[CacheCall] = RequestTrace("test_cache_calls")
    cache = TraceableAdapter(ArrayAdapter(), "app", trace)

    _ = await cache.get_item("a")

    assert trace.entries() == ()


async def test_concurrent_requests_each_see_only_their_own_calls() -> None:
    trace: RequestTrace[CacheCall] = RequestTrace("test_cache_calls")
    cache = TraceableAdapter(ArrayAdapter(), "app", trace)
    both_recorded = anyio.Event()
    recorded: list[str] = []
    seen: dict[str, tuple[str, ...]] = {}

    async def request(key: str) -> None:
        trace.begin()
        _ = await cache.get_item(key)
        recorded.append(key)
        if len(recorded) == 2:
            both_recorded.set()
        await both_recorded.wait()
        seen[key] = tuple(key for call in trace.entries() for key in call.keys)

    async with anyio.create_task_group() as group:
        _ = group.start_soon(request, "first")
        _ = group.start_soon(request, "second")

    assert seen == {"first": ("first",), "second": ("second",)}


async def test_it_stands_in_for_every_interface_of_the_pool() -> None:
    cache, _ = _traced()

    assert isinstance(cache, AdapterInterface)
    assert isinstance(cache, NamespacedPoolInterface)
    assert isinstance(cache, PruneableInterface)


async def test_it_names_the_pool_it_wraps() -> None:
    cache, _ = _traced(NullAdapter())

    assert repr(cache) == "TraceableAdapter(NullAdapter(), 'app')"
