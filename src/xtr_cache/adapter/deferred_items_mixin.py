"""The queue of items saved as deferred, for a pool that commits them in one batch."""

from __future__ import annotations

import copy
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Self

from typing_extensions import override
from xtr_cache_contracts import CacheItemPoolInterface

from xtr_cache.cache_item import CacheItem

if TYPE_CHECKING:
    from collections.abc import Iterable

    from xtr_cache_contracts import ItemInterface

__all__ = ["DeferredItemsMixin"]


class DeferredItemsMixin(CacheItemPoolInterface, ABC):
    """Queues saved items until :meth:`commit`, which the pool implements.

    :meth:`save` is a deferred save committed at once, so a pool writes in one
    place only. What is queued is the pool's to drop when the keys are
    deleted or cleared, and to commit before a queued key is read.
    """

    _deferred: dict[str, CacheItem]

    @abstractmethod
    @override
    async def commit(self) -> bool:
        """Store every queued item."""

    @override
    async def save(self, item: ItemInterface, /) -> bool:
        if not isinstance(item, CacheItem):
            return False

        self._deferred[item.key] = item
        return await self.commit()

    @override
    async def save_deferred(self, item: ItemInterface, /) -> bool:
        if not isinstance(item, CacheItem):
            return False

        self._deferred[item.key] = item
        return True

    async def reset(self) -> None:
        """Commit what was queued, so it does not wait for a commit nothing will call."""
        if self._deferred:
            _ = await self.commit()

    async def _commit_if_queued(self, keys: Iterable[str]) -> None:
        """Commit first when any of ``keys`` is queued, so a read never misses what was saved."""
        if any(key in self._deferred for key in keys):
            _ = await self.commit()

    def _forget_deferred(self, keys: Iterable[str]) -> None:
        """Drop the queued items of ``keys``, which are being deleted."""
        for key in keys:
            _ = self._deferred.pop(key, None)

    def _drop_deferred(self, prefix: str) -> None:
        """Drop the queued items whose key starts with ``prefix``, which are being cleared."""
        self._deferred = {
            key: item for key, item in self._deferred.items() if not key.startswith(prefix)
        }

    def _unqueued_copy(self) -> Self:
        """Return a shallow copy of this pool with nothing queued, for a sub-namespace view."""
        clone = copy.copy(self)
        clone._deferred = {}  # noqa: SLF001 — a copy of this very class.
        return clone
