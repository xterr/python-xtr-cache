"""Unit tests for :mod:`xtr_cache.bundle._profiler`; registering it is integration-tested."""

from __future__ import annotations

from xtr_http_kernel.data_collector import RequestTrace

from xtr_cache import ArrayAdapter, TagAwareAdapter
from xtr_cache.bundle._profiler import PoolTracer
from xtr_cache.data_collector import CacheCall, TraceableAdapter, TraceableTagAwareAdapter


def _tracer() -> PoolTracer:
    trace: RequestTrace[CacheCall] = RequestTrace("test_cache_calls")
    return PoolTracer(trace)


def test_a_pool_without_tags_is_traced_by_the_plain_decorator() -> None:
    pool = ArrayAdapter()

    traced = _tracer()("app", pool)

    assert isinstance(traced, TraceableAdapter)
    assert not isinstance(traced, TraceableTagAwareAdapter)
    assert traced.pool is pool


def test_a_pool_with_tags_is_traced_as_one() -> None:
    pool = TagAwareAdapter(ArrayAdapter())

    traced = _tracer()("tagged", pool)

    assert isinstance(traced, TraceableTagAwareAdapter)
    assert traced.pool is pool
