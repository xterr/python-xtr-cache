from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, final

import pytest
from xtr_lock import InMemoryStore, LockFactory

from tests.support.recording_logger import RecordingLogger
from xtr_cache import ArrayAdapter, CacheItem, InvalidArgumentError, ItemInterface, LockRegistry

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

pytestmark = pytest.mark.anyio


def _registry(
    store: InMemoryStore,
    *,
    slots: int = 20,
    wait: float = 30.0,
) -> tuple[LockRegistry, RecordingLogger]:
    registry = LockRegistry(LockFactory(store), slots=slots, wait=wait)
    logger = RecordingLogger()
    registry.set_logger(logger)
    return registry, logger


async def _mine() -> str:
    return "mine"


async def _unreachable() -> ItemInterface:
    raise AssertionError


@final
class _Holder:
    """Holds a key's slot, computing until released."""

    def __init__(
        self,
        registry: LockRegistry,
        value: str,
        before_return: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._registry = registry
        self._value = value
        self._before_return = before_return
        self._computing = asyncio.Event()
        self._release = asyncio.Event()
        self.task: asyncio.Task[str] | None = None

    async def start(self, key: str = "k") -> None:
        """Take the slot of ``key`` and hold it."""
        self.task = asyncio.create_task(self._registry.compute(key, self._compute, _unreachable))
        _ = await self._computing.wait()

    async def finish(self) -> str:
        """Let go of the slot and return what was computed."""
        self._release.set()
        assert self.task is not None
        return await self.task

    async def _compute(self) -> str:
        self._computing.set()
        _ = await self._release.wait()
        if self._before_return is not None:
            await self._before_return()
        return self._value


async def _wait_then(finish: _Holder, waiting: Awaitable[str]) -> tuple[str, str]:
    """Start ``waiting``, give it time to queue on the slot, then let the holder finish."""
    task = asyncio.ensure_future(waiting)
    await asyncio.sleep(0.05)
    return await finish.finish(), await task


async def test_the_holder_of_a_slot_computes() -> None:
    registry, logger = _registry(InMemoryStore())

    assert await registry.compute("k", _mine, _unreachable) == "mine"
    assert logger.messages("info") == ['Lock acquired, now computing item "{key}"']


async def test_a_caller_waiting_on_the_slot_reads_what_the_holder_saved() -> None:
    store = InMemoryStore()
    pool = ArrayAdapter()

    async def save() -> None:
        _ = await pool.save((await pool.get_item("k")).set("saved"))

    async def read() -> CacheItem:
        return await pool.get_item("k")

    holder = _Holder(_registry(store)[0], "saved", save)
    waiter, logger = _registry(store)
    await holder.start()

    assert await _wait_then(holder, waiter.compute("k", _unreachable_compute, read)) == (
        "saved",
        "saved",
    )
    assert logger.messages("info") == [
        'Item "{key}" is locked, waiting for it to be released',
        'Item "{key}" retrieved after lock was released',
    ]


async def test_a_waiter_that_finds_nothing_saved_tries_again_and_computes() -> None:
    store = InMemoryStore()
    holder = _Holder(_registry(store)[0], "not saved")
    waiter, logger = _registry(store)

    async def read() -> CacheItem:
        return CacheItem("k")

    await holder.start()

    assert await _wait_then(holder, waiter.compute("k", _mine, read)) == ("not saved", "mine")
    assert 'Item "{key}" not found while lock was released, retrying' in logger.messages("info")


async def test_forcing_computes_again_after_waiting() -> None:
    store = InMemoryStore()
    holder = _Holder(_registry(store)[0], "theirs")
    waiter, _ = _registry(store)
    await holder.start()

    waiting = waiter.compute("k", _mine, _unreachable, force=True)

    assert await _wait_then(holder, waiting) == ("theirs", "mine")


async def test_a_waiter_that_waited_too_long_computes_anyway_and_evicts_the_slot() -> None:
    store = InMemoryStore()
    holder = _Holder(_registry(store)[0], "late")
    waiter, logger = _registry(store, wait=0.05)
    await holder.start()

    assert await waiter.compute("k", _mine, _unreachable) == "mine"
    assert logger.messages("warning") == ['Lock on item "{key}" timed out, evicting its slot']

    logger.records.clear()
    assert await asyncio.wait_for(waiter.compute("k", _mine, _unreachable), timeout=0.02) == "mine"
    assert logger.messages("info") == ['Lock acquired, now computing item "{key}"']
    assert await holder.finish() == "late"


async def test_with_every_slot_evicted_values_are_computed_without_locking() -> None:
    store = InMemoryStore()
    holder = _Holder(_registry(store, slots=1)[0], "late")
    waiter, logger = _registry(store, slots=1, wait=0.05)
    await holder.start()
    _ = await waiter.compute("k", _mine, _unreachable)
    logger.records.clear()

    assert (
        await asyncio.wait_for(waiter.compute("other", _mine, _unreachable), timeout=0.02) == "mine"
    )
    assert logger.records == []
    assert await holder.finish() == "late"


def test_a_registry_needs_slots_and_a_wait() -> None:
    with pytest.raises(InvalidArgumentError, match="at least one slot"):
        _ = LockRegistry(LockFactory(InMemoryStore()), slots=0)
    with pytest.raises(InvalidArgumentError, match="positive time"):
        _ = LockRegistry(LockFactory(InMemoryStore()), wait=0)


def test_it_describes_itself() -> None:
    registry = LockRegistry(LockFactory(InMemoryStore()), slots=3, wait=1.5)

    assert registry.slots == 3
    assert registry.wait == 1.5
    assert repr(registry).endswith("slots=3, wait=1.5)")


async def _unreachable_compute() -> str:
    raise AssertionError
