"""Fetch-or-compute on a pool of :class:`CacheItem`: one computation per key, timed."""

from __future__ import annotations

import asyncio
import math
from abc import ABC, abstractmethod
from contextvars import ContextVar
from typing import TYPE_CHECKING, Final, TypeVar, cast

from typing_extensions import override
from xtr_cache_contracts import CacheMixin
from xtr_clock import Clock
from xtr_logging_contracts import LoggerAware

if TYPE_CHECKING:
    from xtr_cache_contracts import Callback, ItemInterface, Metadata
    from xtr_clock import ClockInterface

    from xtr_cache.cache_item import CacheItem
    from xtr_cache.lock_registry import LockRegistry

__all__ = ["ContractsMixin"]

_T = TypeVar("_T")

_CLOCK_IN_FORCE: Final = Clock()

_COMPUTING: ContextVar[frozenset[tuple[int, str]]] = ContextVar(
    "xtr_cache_computing",
    default=frozenset(),
)
"""The computations the running task is inside of: its flight registry, and the scoped key."""

_FAILED: Final = object()
"""What a shared computation resolves to when its owner failed or was cancelled."""


class ContractsMixin(CacheMixin, LoggerAware, ABC):
    """Fetch-or-compute on a pool of :class:`~xtr_cache.cache_item.CacheItem`.

    Built on :class:`~xtr_cache_contracts.CacheMixin`'s template, adjusting how
    a missing value is computed:

    - It is saved with how long it took, which — with its expiry — is what
      makes early recomputation possible on a later read.
    - Concurrent misses on one key in this process share one computation. If
      it fails or is cancelled, each of the others computes for itself.
    - With a :class:`~xtr_cache.lock_registry.LockRegistry`, misses in every
      process sharing its locks share one computation too.
    - A callback reading its own key — directly or through what it calls —
      computes without saving, instead of waiting on itself.

    Computations are keyed by :meth:`_scope` and the key, so pools on one
    backend under different namespaces never wait on each other.
    """

    _lock_registry: LockRegistry | None = None
    _clock: ClockInterface = _CLOCK_IN_FORCE
    _in_flight: dict[str, asyncio.Future[object]]

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
        if (id(flights), scoped) in _COMPUTING.get():
            value = await callback(item)
            _ = item.set(value)
            return value

        shared = flights.get(scoped)
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
        token = _COMPUTING.set(_COMPUTING.get() | {(id(self._flights()), scoped)})
        started = self._now()
        try:
            value = await callback(item)
        finally:
            _COMPUTING.reset(token)

        ctime = math.ceil(1000 * (self._now() - started))
        _ = item.set(value).record_computation(ctime)
        if metadata is not None:
            _report(metadata, item, ctime)
        if not await self.save(item) and metadata is not None:
            metadata["save_failed"] = True

        return value

    def _flights(self) -> dict[str, asyncio.Future[object]]:
        """Return the computations in progress, by scoped key; views of this pool share them."""
        try:
            return self._in_flight
        except AttributeError:
            self._in_flight = {}
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
