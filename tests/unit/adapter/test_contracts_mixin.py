from __future__ import annotations

import asyncio
import math
from typing import TYPE_CHECKING

import pytest
from xtr_cache_contracts import cache_mixin
from xtr_clock.testing import mock_time
from xtr_lock import InMemoryStore, LockFactory

from tests.support.callbacks import Computation
from tests.support.recording_logger import RecordingLogger
from tests.support.scripted_adapter import ScriptedAdapter
from xtr_cache import (
    ArrayAdapter,
    FilesystemAdapter,
    InvalidArgumentError,
    ItemInterface,
    LockRegistry,
    Metadata,
    TagAwareAdapter,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.anyio

NOON = "2024-04-09 12:00:00"


def _logged_registry() -> tuple[LockRegistry, RecordingLogger]:
    registry = LockRegistry(LockFactory(InMemoryStore()))
    logger = RecordingLogger()
    registry.set_logger(logger)
    return registry, logger


async def test_concurrent_misses_on_one_key_share_one_computation() -> None:
    pool = ArrayAdapter()
    compute = Computation(42, held=True)

    tasks = [asyncio.create_task(pool.get("k", compute)) for _ in range(5)]
    await asyncio.sleep(0)
    compute.release()

    assert await asyncio.gather(*tasks) == [42] * 5
    assert compute.calls == 1


async def test_when_the_shared_computation_fails_the_others_compute_side_by_side() -> None:
    pool = ArrayAdapter()
    failing = Computation(0, held=True, fails_with=LookupError("backend down"))
    following = Computation(7, held=True)

    leader = asyncio.create_task(pool.get("k", failing))
    _ = await failing.started.wait()
    followers = [asyncio.create_task(pool.get("k", following)) for _ in range(3)]
    await asyncio.sleep(0)  # the followers now wait on the leader's computation
    failing.release()
    with pytest.raises(LookupError):
        await leader
    await asyncio.sleep(0)

    assert following.calls == 3  # all three computing at once, not one after another
    following.release()
    assert await asyncio.gather(*followers) == [7, 7, 7]


async def test_a_callback_reading_its_own_key_computes_without_waiting_on_itself() -> None:
    pool = ArrayAdapter()

    async def outer(item: ItemInterface) -> str:
        del item
        return f"outer({await pool.get('k', Computation('inner'))})"

    assert await pool.get("k", outer) == "outer(inner)"
    assert (await pool.get_item("k")).get() == "outer(inner)"


async def test_an_infinite_beta_recomputes_a_hit() -> None:
    pool = ArrayAdapter()
    _ = await pool.get("k", Computation("old"))

    assert await pool.get("k", Computation("new"), beta=math.inf) == "new"


@pytest.mark.parametrize("beta", [-1.0, math.nan])
async def test_a_negative_or_undefined_beta_is_refused(beta: float) -> None:
    with pytest.raises(InvalidArgumentError, match="beta"):
        _ = await ArrayAdapter().get("k", Computation(1), beta=beta)


async def test_the_metadata_reports_expiry_cost_and_tags_or_their_absence() -> None:
    pool = ArrayAdapter()

    with mock_time(NOON) as clock:
        metadata: Metadata = {}
        _ = await pool.get(
            "timed", Computation(1, lifetime=60, took=0.25, clock=clock), metadata=metadata
        )
        assert metadata == {"expiry": clock.now().timestamp() - 0.25 + 60, "ctime": 250}

        stale: Metadata = {"expiry": 1.0, "ctime": 1, "tags": ("x",)}
        _ = await pool.get("untimed", Computation(1), metadata=stale)
        assert stale == {"ctime": 0}


async def test_the_tags_a_callback_adds_are_reported_in_the_metadata() -> None:
    metadata: Metadata = {}

    _ = await TagAwareAdapter(ArrayAdapter()).get(
        "k", Computation(1, tags=("red",)), metadata=metadata
    )

    assert metadata.get("tags") == ("red",)


async def test_a_value_that_cannot_be_saved_is_returned_and_reported() -> None:
    pool = ScriptedAdapter()
    pool.fail.add("save")
    metadata: Metadata = {}

    assert await pool.get("k", Computation(1), metadata=metadata) == 1
    assert metadata.get("save_failed") is True


async def test_a_value_living_for_the_default_lifetime_is_stored_ready_to_refresh_early() -> None:
    pool = ArrayAdapter(default_lifetime=60)

    with mock_time(NOON) as clock:
        _ = await pool.get("k", Computation(1, took=0.5, clock=clock))

        assert (await pool.get_item("k")).metadata == {
            "ctime": 500,
            "expiry": clock.now().timestamp() + 60,
        }


@pytest.mark.parametrize(
    ("lived", "beta", "recomputed"),
    [
        (8, None, True),  # one second of life left, less than the second it took, scaled
        (1, None, False),  # far from expiry
        (8, 0.0, False),  # close, but early recomputation switched off
    ],
)
async def test_a_hit_is_recomputed_early_only_close_to_its_expiry(
    monkeypatch: pytest.MonkeyPatch,
    lived: float,
    beta: float | None,
    recomputed: bool,
) -> None:
    monkeypatch.setattr(cache_mixin, "_draw", lambda: 0.1)
    pool = ArrayAdapter()
    logger = RecordingLogger()
    pool.set_logger(logger)

    with mock_time(NOON) as clock:
        _ = await pool.get("k", Computation("first", lifetime=10, took=1, clock=clock))
        clock.sleep(lived)

        value = await pool.get("k", Computation("fresh"), beta=beta)

    assert value == ("fresh" if recomputed else "first")
    elected = 'Item "{key}" elected for early recomputation {delta}s before its expiration'
    assert (elected in logger.messages("info")) is recomputed


async def test_with_a_lock_registry_a_miss_is_computed_under_its_slot_scoped_by_namespace() -> None:
    registry, logger = _logged_registry()
    pool = ScriptedAdapter("ns")
    pool.set_lock_registry(registry)

    assert await pool.get("k", Computation(1)) == 1

    assert logger.messages("info") == ['Lock acquired, now computing item "{key}"']
    _, _, context = logger.records[0]
    assert context["key"] == "ns:k"


async def test_pools_sharing_a_backend_and_a_lock_registry_compute_a_value_once(
    tmp_path: Path,
) -> None:
    registry, _ = _logged_registry()
    first = FilesystemAdapter("pool", directory=tmp_path)
    second = FilesystemAdapter("pool", directory=tmp_path)
    for pool in (first, second):
        pool.set_lock_registry(registry)
    slow = Computation("computed once", held=True)
    never = Computation("computed twice")

    holding = asyncio.create_task(first.get("k", slow))
    _ = await slow.started.wait()
    waiting = asyncio.create_task(second.get("k", never))
    await asyncio.sleep(0.05)
    slow.release()

    assert await asyncio.gather(holding, waiting) == ["computed once", "computed once"]
    assert never.calls == 0
