"""The cache panel of the profiler, registered when the http kernel profiles requests.

Imported only then: it needs xtr-http-kernel, which a cache never does.
"""

from __future__ import annotations

from typing import Final, final

from xtr_clock import MonotonicClock
from xtr_dependency_injection import ServiceConfigurator
from xtr_http_kernel.data_collector import DATA_COLLECTOR_TAG, RequestTrace

from xtr_cache.adapter.adapter_interface import AdapterInterface
from xtr_cache.adapter.tag_aware_adapter_interface import TagAwareAdapterInterface
from xtr_cache.data_collector import (
    CacheCall,
    CacheDataCollector,
    TraceableAdapter,
    TraceableTagAwareAdapter,
)

__all__ = ["PoolTracer", "register_profiler"]

_NAME: Final = "cache"
_TEMPLATE: Final = "@xtr_cache/collector/cache.html.j2"
_PRIORITY: Final = 275


@final
class PoolTracer:
    """Wraps each pool the bundle builds, so its calls reach the collector's trace."""

    __slots__ = ("_clock", "_trace")

    def __init__(self, trace: RequestTrace[CacheCall]) -> None:
        self._trace = trace
        self._clock = MonotonicClock()

    def __call__(self, name: str, pool: AdapterInterface) -> AdapterInterface:
        """Return ``pool``, recording its calls under ``name``; tag-aware when it has tags."""
        if isinstance(pool, TagAwareAdapterInterface):
            return TraceableTagAwareAdapter(pool, name, self._trace, self._clock)
        return TraceableAdapter(pool, name, self._trace, self._clock)


def register_profiler(services: ServiceConfigurator) -> PoolTracer:
    """Register the ``cache`` collector, and return what traces the pools into it."""
    trace: RequestTrace[CacheCall] = RequestTrace("cache_calls")
    _ = services.instance(CacheDataCollector(trace)).add_tag(
        DATA_COLLECTOR_TAG, name=_NAME, template=_TEMPLATE, priority=_PRIORITY
    )
    return PoolTracer(trace)
