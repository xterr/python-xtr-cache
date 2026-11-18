"""Unit tests for :class:`xtr_cache.data_collector.TraceableTagAwareAdapter`."""

from __future__ import annotations

import pytest
from xtr_clock import MockClock
from xtr_http_kernel.data_collector import RequestTrace

from tests.support.callbacks import Computation
from xtr_cache import ArrayAdapter, TagAwareAdapter, TagAwareAdapterInterface
from xtr_cache.data_collector import CacheCall, TraceableTagAwareAdapter

pytestmark = pytest.mark.anyio


def _traced() -> tuple[TraceableTagAwareAdapter, RequestTrace[CacheCall]]:
    trace: RequestTrace[CacheCall] = RequestTrace("test_cache_calls")
    trace.begin()
    pool = TagAwareAdapter(ArrayAdapter())
    return TraceableTagAwareAdapter(pool, "tagged", trace, MockClock()), trace


async def test_an_invalidation_is_recorded_with_its_tags_as_keys() -> None:
    cache, trace = _traced()

    assert await cache.invalidate_tags(tag for tag in ("customer.7", "customer.8"))

    assert trace.entries() == (
        CacheCall(
            "tagged", "invalidate_tags", ("customer.7", "customer.8"), 0, 0, 0.0, result=True
        ),
    )


async def test_an_invalidated_tag_drops_the_values_carrying_it() -> None:
    cache, _ = _traced()
    _ = await cache.get("invoice.7", Computation("total", tags=("customer.7",)))

    _ = await cache.invalidate_tags(["customer.7"])

    assert not await cache.has_item("invoice.7")


async def test_a_sub_namespace_view_keeps_its_tags() -> None:
    cache, _ = _traced()

    view = cache.with_sub_namespace("reports")

    assert isinstance(view, TraceableTagAwareAdapter)


async def test_it_stands_in_for_a_pool_with_tags() -> None:
    cache, _ = _traced()

    assert isinstance(cache, TagAwareAdapterInterface)
