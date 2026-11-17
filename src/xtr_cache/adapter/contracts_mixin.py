"""Fetch-or-compute on a pool of :class:`CacheItem`: one computation per key, timed."""

from __future__ import annotations

import asyncio
import math
from abc import ABC, abstractmethod
from contextvars import ContextVar
from typing import TYPE_CHECKING, Final, TypeVar, cast, final
from weakref import WeakKeyDictionary

from typing_extensions import override
from xtr_cache_contracts import CacheMixin
from xtr_clock import Clock
from xtr_logging_contracts import LoggerAware

if TYPE_CHECKING:
    from collections.abc import Iterable

    from xtr_cache_contracts import Callback, ItemInterface, Metadata
    from xtr_clock import ClockInterface

    from xtr_cache.cache_item import CacheItem
    from xtr_cache.lock_registry import LockRegistry

__all__ = ["ContractsMixin"]

_T = TypeVar("_T")

_CLOCK_IN_FORCE: Final = Clock()


@final
class _Computing:
    """A computation the running task is inside of, open until its callback returns.

    It holds its flight registry itself, never its id, which a registry built
    after one was freed may take over. The tags invalidated while it ran are
    gathered here, so a value computed from what they covered is not saved.
    """

    __slots__ = ("flights", "invalidated", "open", "scoped")

    def __init__(self, flights: dict[str, asyncio.Future[object]], scoped: str) -> None:
        self.flights = flights
        self.scoped = scoped
        self.open = True
        self.invalidated: set[str] = set()


@final
class _Shared:
    """What a pool and its sub-namespace views share: flights by loop, and the open computations.

    Flights are kept per event loop — a future belongs to the loop it was made
    on — under the loop itself, never its id.
    """

    __slots__ = ("by_loop", "computing")

    def __init__(self) -> None:
        self.by_loop: WeakKeyDictionary[
            asyncio.AbstractEventLoop, dict[str, asyncio.Future[object]]
        ] = WeakKeyDictionary()
        self.computing: set[_Computing] = set()


_COMPUTING: ContextVar[tuple[_Computing, ...]] = ContextVar(
    "xtr_cache_computing",
    default=(),
)
"""The computations the running task is inside of; a task outliving one carries it closed."""

_FAILED: Final = object()
"""What a shared computation resolves to when its owner failed or was cancelled."""


class ContractsMixin(CacheMixin, LoggerAware, ABC):
    """Fetch-or-compute on a pool of :class:`~xtr_cache.cache_item.CacheItem`.

    Built on :class:`~xtr_cache_contracts.CacheMixin`'s template, adjusting how
    a missing value is computed:

    - It is saved with how long it took, which — with its expiry — is what
      makes early recomputation possible on a later read.
    - Concurrent misses on one key in this process share one computation, and
      its result: each of them gets the very object computed, so change it
      only after copying it. What is cached stays apart. If the computation
      fails or is cancelled, each of the others computes for itself.
    - With a :class:`~xtr_cache.lock_registry.LockRegistry`, misses in every
      process sharing its locks share one computation too.
    - A callback reading its own key — directly or through what it calls —
      computes without saving, instead of waiting on itself.
    - A forced recomputation (``beta`` infinite) runs its own callback, never
      joining one already in progress.
    - A value whose tags were invalidated while it was computed is returned
      but not saved: it was computed from what the invalidation retired.
      This sees the invalidations of this process only.

    Computations are keyed by :meth:`_scope` and the key, so pools on one
    backend under different namespaces never wait on each other, and by the
    running event loop, so two loops never wait on each other's futures.
    """

    _lock_registry: LockRegistry | None = None
    _clock: ClockInterface = _CLOCK_IN_FORCE
    _in_flight: _Shared

    @abstractmethod
    @override
    async def get_item(self, key: str, /) -> CacheItem:
        """Return the item for ``key``, a hit or a miss."""

    def set_lock_registry(self, registry: LockRegistry | None) -> None:
        """Compute missing values under ``registry``'s locks; ``None`` for this process alone."""
        self._lock_registry = registry

    @abstractmethod
    def _scope(self) -> str:
        """Return what sets this pool's keys apart from another's on the same backend."""

    @override
    def _now(self) -> float:
        return self._clock.now().timestamp()

    @override
    def _on_elected(self, item: ItemInterface, remaining: float) -> None:
        self.logger.info(
            'Item "{key}" elected for early recomputation {delta}s before its expiration',
            {"key": item.key, "delta": f"{remaining:.1f}"},
        )

    @override
    async def _compute(
        self,
        item: ItemInterface,
        callback: Callback[_T],
        beta: float,
        metadata: Metadata | None,
    ) -> _T:
        """Compute the value once for every concurrent caller, under the lock registry if any."""
        # The template hands back what get_item returned, which here is always a CacheItem.
        item = cast("CacheItem", item)
        flights = self._flights()
        scoped = self._scope() + item.key
        if any(
            computing.open and computing.flights is flights and computing.scoped == scoped
            for computing in _COMPUTING.get()
        ):
            value = await callback(item)
            _ = item.set(value)
            return value

        shared = None if math.isinf(beta) else flights.get(scoped)
        if shared is not None:
            result = await asyncio.shield(shared)
            if result is not _FAILED:
                # Computed by the same kind of callback for the same key: the caller's promise.
                return cast("_T", result)
            # Queueing behind another attempt would make every caller wait for every failure.
            return await self._compute_and_save(item, callback, metadata, scoped)

        future: asyncio.Future[object] = asyncio.get_running_loop().create_future()
        flights[scoped] = future
        try:
            value = await self._compute_locked(item, callback, beta, metadata, scoped)
        except BaseException:
            future.set_result(_FAILED)
            raise
        else:
            future.set_result(value)
            return value
        finally:
            if flights.get(scoped) is future:
                del flights[scoped]

    async def _compute_locked(
        self,
        item: CacheItem,
        callback: Callback[_T],
        beta: float,
        metadata: Metadata | None,
        scoped: str,
    ) -> _T:
        """Compute under the lock registry's slot for ``scoped``, when there is a registry."""
        if self._lock_registry is None:
            return await self._compute_and_save(item, callback, metadata, scoped)

        async def compute() -> _T:
            return await self._compute_and_save(item, callback, metadata, scoped)

        async def read() -> ItemInterface:
            return await self.get_item(item.key)

        return await self._lock_registry.compute(scoped, compute, read, force=math.isinf(beta))

    async def _compute_and_save(
        self,
        item: CacheItem,
        callback: Callback[_T],
        metadata: Metadata | None,
        scoped: str,
    ) -> _T:
        """Run ``callback``, record how long it took, save the value, and report it."""
        open_computations = self._shared().computing
        computing = _Computing(self._flights(), scoped)
        open_computations.add(computing)
        token = _COMPUTING.set((*_COMPUTING.get(), computing))
        started = self._now()
        try:
            value = await callback(item)
        finally:
            computing.open = False
            open_computations.discard(computing)
            _COMPUTING.reset(token)

        ctime = math.ceil(1000 * (self._now() - started))
        _ = item.set(value).record_computation(ctime)
        if metadata is not None:
            _report(metadata, item, ctime)
        if not computing.invalidated.isdisjoint(item.pending_tags):
            if metadata is not None:
                metadata["save_failed"] = True
        elif not await self.save(item) and metadata is not None:
            metadata["save_failed"] = True

        return value

    def _invalidated_while_computing(self, tags: Iterable[str]) -> None:
        """Tell every computation in progress that ``tags`` were invalidated meanwhile."""
        invalidated = set(tags)
        for computing in self._shared().computing:
            computing.invalidated.update(invalidated)

    def _flights(self) -> dict[str, asyncio.Future[object]]:
        """Return the running loop's computations in progress, by scoped key."""
        by_loop = self._shared().by_loop
        loop = asyncio.get_running_loop()
        flights = by_loop.get(loop)
        if flights is None:
            flights = by_loop[loop] = {}
        return flights

    def _shared(self) -> _Shared:
        """Return what this pool shares with its views; made on first use, or before a view."""
        try:
            return self._in_flight
        except AttributeError:
            self._in_flight = _Shared()
            return self._in_flight


def _report(metadata: Metadata, item: CacheItem, ctime: int) -> None:
    """Tell the caller what the computed value is stored with, dropping what no longer holds."""
    metadata["ctime"] = ctime
    if item.expiry is not None:
        metadata["expiry"] = item.expiry
    else:
        _ = metadata.pop("expiry", None)
    if item.pending_tags:
        metadata["tags"] = item.pending_tags
    else:
        _ = metadata.pop("tags", None)
