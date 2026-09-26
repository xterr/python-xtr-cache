"""Lets one holder at a time compute a missing value, among everyone sharing a lock store."""

from __future__ import annotations

import asyncio
import zlib
from typing import TYPE_CHECKING, Final, TypeVar, cast, final

from typing_extensions import override
from xtr_logging_contracts import LoggerAware

from .exception import InvalidArgumentError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from xtr_cache_contracts import ItemInterface
    from xtr_lock import LockFactory

__all__ = ["LockRegistry"]

_T = TypeVar("_T")

DEFAULT_SLOTS: Final = 20
"""How many values may be computed at once, across every process sharing the locks."""

DEFAULT_WAIT: Final = 30.0
"""How long a caller waits for another to compute a value before computing it too, in seconds."""


@final
class LockRegistry(LoggerAware):
    """Protects a backend from a stampede: one computation per key, a bounded number at once.

    Keys are spread over a fixed number of slots, each a lock. The caller that
    takes a key's slot computes and saves the value; every other caller missing
    the same key waits for the slot to be released and reads what was saved.
    So among every process sharing the lock store — every process on a machine
    with file locks, every machine with Redis — one computes each value, and
    no more than ``slots`` compute at once.

    A caller that waited longer than ``wait`` stops waiting and computes the
    value itself: a stuck holder must not stall every reader of the key. The
    slot is then evicted, in this process, so its keys spread over the other
    slots instead of waiting on it in turn; with every slot evicted, values
    are computed without locking.
    """

    __slots__ = ("_available", "_locks", "_prefix", "_slots", "_wait")

    _locks: LockFactory
    _slots: int
    _available: list[int]
    _wait: float
    _prefix: str

    def __init__(
        self,
        locks: LockFactory,
        *,
        slots: int = DEFAULT_SLOTS,
        wait: float = DEFAULT_WAIT,
        prefix: str = "xtr-cache.",
    ) -> None:
        """Take slots' locks from ``locks``.

        Args:
            locks: Where the locks come from; its store decides who shares them.
            slots: How many values may be computed at once.
            wait: How long to wait for another caller's computation, in seconds.
            prefix: Put in front of each slot's number to name its lock.

        Raises:
            InvalidArgumentError: When ``slots`` or ``wait`` is not positive.
        """
        if slots < 1:
            raise InvalidArgumentError(f"A lock registry needs at least one slot, got {slots}.")
        if wait <= 0:
            raise InvalidArgumentError(f"A lock registry must wait a positive time, got {wait}.")

        self._locks = locks
        self._slots = slots
        self._available = list(range(slots))
        self._wait = wait
        self._prefix = prefix

    async def compute(
        self,
        key: str,
        compute: Callable[[], Awaitable[_T]],
        read: Callable[[], Awaitable[ItemInterface]],
        *,
        force: bool = False,
    ) -> _T:
        """Return the value for ``key``, computed here or by whoever held its slot.

        Args:
            key: The key whose value is missing.
            compute: Computes the value and saves it, holding the slot.
            read: Reads the key again, once another holder has released it.
            force: Compute even when another holder saved a value meanwhile.

        Returns:
            The value computed here, or the one read after waiting.
        """
        slot = self._slot(key)
        if slot is None:
            return await compute()
        resource = f"{self._prefix}{slot}"
        context: dict[str, object] = {"key": key, "slot": resource}

        while True:
            lock = self._locks.create_lock(resource)
            if await lock.acquire():
                self.logger.info('Lock acquired, now computing item "{key}"', context)
                try:
                    return await compute()
                finally:
                    await lock.release()

            self.logger.info('Item "{key}" is locked, waiting for it to be released', context)
            try:
                async with asyncio.timeout(self._wait):
                    _ = await lock.acquire_read(blocking=True)
            except TimeoutError:
                self.logger.warning('Lock on item "{key}" timed out, evicting its slot', context)
                self._evict(slot)
                return await compute()
            await lock.release()

            if force:
                continue

            item = await read()
            if item.is_hit():
                self.logger.info('Item "{key}" retrieved after lock was released', context)
                # The key's value was saved by the same kind of callback: the caller's promise.
                return cast("_T", item.get())

            self.logger.info('Item "{key}" not found while lock was released, retrying', context)

    def _slot(self, key: str) -> int | None:
        """Return the slot ``key`` computes under; ``None`` once every slot was evicted."""
        if not self._available:
            return None
        return self._available[zlib.crc32(key.encode()) % len(self._available)]

    def _evict(self, slot: int) -> None:
        """Stop using ``slot``, whose holder is stuck, so later callers do not wait on it too."""
        if slot in self._available:
            self._available.remove(slot)

    @property
    def slots(self) -> int:
        """How many values may be computed at once."""
        return self._slots

    @property
    def wait(self) -> float:
        """How long a caller waits for another's computation, in seconds."""
        return self._wait

    @override
    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._locks!r}, slots={self._slots}, wait={self._wait})"
