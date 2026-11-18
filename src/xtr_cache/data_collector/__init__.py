"""The profiler's cache panel: every pool call a profiled request made.

:class:`TraceableAdapter` — :class:`TraceableTagAwareAdapter` for a pool with
tags — wraps a pool and records each call into a request trace as a
:class:`CacheCall`; :class:`CacheDataCollector` reads the trace back into the
request's profile. The bundle wraps every pool only while the http kernel
profiles requests.
"""

from __future__ import annotations

from .cache_call import CacheCall
from .cache_data_collector import CacheDataCollector
from .traceable_adapter import TraceableAdapter
from .traceable_tag_aware_adapter import TraceableTagAwareAdapter

__all__ = [
    "CacheCall",
    "CacheDataCollector",
    "TraceableAdapter",
    "TraceableTagAwareAdapter",
]
