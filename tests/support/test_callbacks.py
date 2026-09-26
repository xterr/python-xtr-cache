"""The computation helper does what each of its options says."""

from __future__ import annotations

import asyncio

import pytest
from xtr_clock.testing import mock_time

from tests.support.callbacks import Computation
from xtr_cache import CacheItem

pytestmark = pytest.mark.anyio


async def test_it_returns_its_value_and_records_each_item() -> None:
    compute = Computation("v")
    item = CacheItem("k")

    assert await compute(item) == "v"
    assert compute.items == [item]
    assert compute.calls == 1


async def test_it_sets_the_lifetime_and_tags_and_takes_its_time() -> None:
    with mock_time("2024-04-09 12:00:00") as clock:
        item = CacheItem("k", taggable=True)
        started = clock.now()

        _ = await Computation(1, lifetime=5, tags=("red",), took=2, clock=clock)(item)

        assert item.expiry == started.timestamp() + 5
        assert item.pending_tags == ("red",)
        assert (clock.now() - started).total_seconds() == 2


async def test_a_held_computation_returns_once_released_and_can_fail() -> None:
    compute = Computation(1, held=True, fails_with=LookupError("down"))
    running = asyncio.create_task(compute(CacheItem("k")))
    _ = await compute.started.wait()

    assert not running.done()
    compute.release()
    with pytest.raises(LookupError):
        await running
