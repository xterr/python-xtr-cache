"""The cache panel, through a booted kernel with the http kernel's profiler on and off."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from xtr_dependency_injection import Kernel
from xtr_http_kernel.bundle import HttpKernelBundle
from xtr_http_kernel.data_collector import ProfiledRequest
from xtr_http_kernel.profiler import Profiler

from tests.support.callbacks import Computation
from xtr_cache import (
    AdapterInterface,
    ArrayAdapter,
    CacheInterface,
    TagAwareAdapterInterface,
    TagAwareCacheInterface,
)
from xtr_cache.bundle import CacheBundle
from xtr_cache.data_collector import (
    CacheDataCollector,
    TraceableAdapter,
    TraceableTagAwareAdapter,
)

if TYPE_CHECKING:
    from pathlib import Path

    from xtr_http_message_contracts import ServerRequestInterface

pytestmark = pytest.mark.anyio

APP = "tests.fixtures.app_cache"
PROFILER_ON = "tests.fixtures.profiler_on"

_PROFILED = ProfiledRequest(cast("ServerRequestInterface", object()), 200, {}, {})


def _kernel(tmp_path: Path, *resources: str) -> Kernel:
    return Kernel(
        APP,
        env="test",
        bundles={CacheBundle: {"all": True}, HttpKernelBundle: {"all": True}},
        resources=(APP, *resources),
        environ={"CACHE_TEST_DSN": "array", "CACHE_TEST_DIR": str(tmp_path / "pools")},
    )


@pytest.fixture(autouse=True)
def _profiles_under_tmp_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROFILER_TEST_FOLDER", str(tmp_path / "profiles"))


async def test_the_collector_is_registered_when_requests_are_profiled(tmp_path: Path) -> None:
    async with await _kernel(tmp_path, PROFILER_ON).boot() as booted:
        profiler = await booted.container.get(Profiler)

        assert booted.container.has(CacheDataCollector)
        assert profiler.has("cache")
        assert isinstance(profiler.get("cache"), CacheDataCollector)


async def test_every_pool_is_handed_out_traced_under_each_of_its_interfaces(
    tmp_path: Path,
) -> None:
    async with await _kernel(tmp_path, PROFILER_ON).boot() as booted:
        container = booted.container
        app = await container.get(AdapterInterface, "app")
        tagged = await container.get(TagAwareCacheInterface, "tagged")

        assert isinstance(app, TraceableAdapter)
        assert isinstance(app.pool, ArrayAdapter)
        assert await container.get(CacheInterface) is app
        assert isinstance(tagged, TraceableTagAwareAdapter)
        assert await container.get(TagAwareAdapterInterface, "tagged") is tagged


async def test_the_calls_of_a_profiled_request_are_collected(tmp_path: Path) -> None:
    async with await _kernel(tmp_path, PROFILER_ON).boot() as booted:
        collector = await booted.container.get(CacheDataCollector)
        app = await booted.container.get(CacheInterface)
        tagged = await booted.container.get(TagAwareCacheInterface, "tagged")
        collector.begin_request()

        _ = await app.get("invoice.7", Computation("total"))
        _ = await app.get("invoice.7", Computation("other"))
        _ = await tagged.invalidate_tags(["customer.7"])
        data = collector.late_collect(collector.collect(_PROFILED), _PROFILED)

    calls = cast("list[dict[str, object]]", data["calls"])
    assert [(call["pool"], call["method"], call["hits"], call["misses"]) for call in calls] == [
        ("app", "get", 0, 1),
        ("app", "get", 1, 0),
        ("tagged", "invalidate_tags", 0, 0),
    ]
    assert calls[2]["keys"] == ["customer.7"]
    assert calls[2]["result"] is True
    totals = cast("dict[str, object]", data["totals"])
    assert (totals["calls"], totals["reads"], totals["hits"], totals["misses"]) == (3, 2, 1, 1)
    assert totals["deletes"] == 1
    assert list(cast("dict[str, object]", data["pools"])) == ["app", "tagged"]


async def test_nothing_is_recorded_before_a_profiled_request_begins(tmp_path: Path) -> None:
    async with await _kernel(tmp_path, PROFILER_ON).boot() as booted:
        collector = await booted.container.get(CacheDataCollector)
        app = await booted.container.get(CacheInterface)

        _ = await app.get("invoice.7", Computation("total"))

        assert collector.collect(_PROFILED)["calls"] == []


async def test_without_the_profiler_no_collector_is_registered_and_pools_are_untraced(
    tmp_path: Path,
) -> None:
    async with await _kernel(tmp_path).boot() as booted:
        app = await booted.container.get(AdapterInterface, "app")

        assert not booted.container.has(CacheDataCollector)
        assert isinstance(app, ArrayAdapter)
