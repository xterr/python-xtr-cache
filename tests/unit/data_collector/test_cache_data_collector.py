"""Unit tests for :class:`xtr_cache.data_collector.CacheDataCollector`."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

import anyio
import pytest
from xtr_http_kernel.data_collector import (
    LateDataCollectorInterface,
    ProfiledRequest,
    RequestTrace,
    TracingDataCollectorInterface,
)

from xtr_cache.data_collector import CacheCall, CacheDataCollector

if TYPE_CHECKING:
    from xtr_http_message_contracts import ServerRequestInterface

pytestmark = pytest.mark.anyio

_PROFILED = ProfiledRequest(cast("ServerRequestInterface", object()), 200, {}, {})


def _collector() -> tuple[CacheDataCollector, RequestTrace[CacheCall]]:
    trace: RequestTrace[CacheCall] = RequestTrace("test_cache_calls")
    collector = CacheDataCollector(trace)
    collector.begin_request()
    return collector, trace


def _call(pool: str, method: str, *, hits: int = 0, misses: int = 0) -> CacheCall:
    result = None if method in {"get", "get_item"} else True
    return CacheCall(pool, method, ("invoice.7",), hits, misses, 1.25, result)


async def test_it_is_named_cache_and_traces_the_request() -> None:
    collector, _ = _collector()

    assert collector.name == "cache"
    assert isinstance(collector, TracingDataCollectorInterface)
    assert isinstance(collector, LateDataCollectorInterface)


async def test_every_call_is_kept_in_order_as_plain_data() -> None:
    collector, trace = _collector()
    trace.record(_call("app", "get", misses=1))
    trace.record(_call("app", "save"))

    data = collector.late_collect(collector.collect(_PROFILED), _PROFILED)

    assert data["calls"] == [
        {
            "pool": "app",
            "method": "get",
            "keys": ["invoice.7"],
            "hits": 0,
            "misses": 1,
            "duration_ms": 1.25,
            "result": None,
        },
        {
            "pool": "app",
            "method": "save",
            "keys": ["invoice.7"],
            "hits": 0,
            "misses": 0,
            "duration_ms": 1.25,
            "result": True,
        },
    ]
    assert json.loads(json.dumps(data)) == data


async def test_the_request_and_each_pool_are_totalled() -> None:
    collector, trace = _collector()
    trace.record(_call("app", "get", hits=1))
    trace.record(_call("app", "get_item", misses=1))
    trace.record(_call("app", "save"))
    trace.record(_call("sessions", "delete"))
    trace.record(_call("sessions", "reset"))

    data = collector.late_collect({}, _PROFILED)

    assert data["totals"] == {
        "calls": 5,
        "reads": 2,
        "hits": 1,
        "misses": 1,
        "writes": 1,
        "deletes": 1,
        "duration_ms": 6.25,
    }
    assert data["pools"] == {
        "app": {
            "calls": 3,
            "reads": 2,
            "hits": 1,
            "misses": 1,
            "writes": 1,
            "deletes": 0,
            "duration_ms": 3.75,
        },
        "sessions": {
            "calls": 2,
            "reads": 0,
            "hits": 0,
            "misses": 0,
            "writes": 0,
            "deletes": 1,
            "duration_ms": 2.5,
        },
    }


async def test_a_key_named_like_a_credential_is_masked() -> None:
    collector, trace = _collector()
    trace.record(CacheCall("app", "get_item", ("reset_token.3f9a",), 0, 1, 0.0, None))

    calls = cast("list[dict[str, object]]", collector.collect(_PROFILED)["calls"])

    assert calls[0]["keys"] == ["******"]


async def test_a_request_without_cache_calls_has_empty_totals() -> None:
    collector, _ = _collector()

    data = collector.collect(_PROFILED)

    assert data["calls"] == []
    assert data["pools"] == {}
    assert data["totals"] == {
        "calls": 0,
        "reads": 0,
        "hits": 0,
        "misses": 0,
        "writes": 0,
        "deletes": 0,
        "duration_ms": 0.0,
    }


async def test_concurrent_requests_each_collect_only_their_own_calls() -> None:
    trace: RequestTrace[CacheCall] = RequestTrace("test_cache_calls")
    collector = CacheDataCollector(trace)
    both_recorded = anyio.Event()
    recorded: list[str] = []
    seen: dict[str, object] = {}

    async def request(pool: str) -> None:
        collector.begin_request()
        trace.record(_call(pool, "get_item", hits=1))
        recorded.append(pool)
        if len(recorded) == 2:
            both_recorded.set()
        await both_recorded.wait()
        seen[pool] = list(cast("dict[str, object]", collector.collect(_PROFILED)["pools"]))

    async with anyio.create_task_group() as group:
        _ = group.start_soon(request, "app")
        _ = group.start_soon(request, "sessions")

    assert seen == {"app": ["app"], "sessions": ["sessions"]}
