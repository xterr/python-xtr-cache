"""What every pool of this library is: an item pool, a cache, and resettable."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from typing_extensions import override
from xtr_cache_contracts import CacheInterface, CacheItemPoolInterface

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from xtr_cache.cache_item import CacheItem

__all__ = ["AdapterInterface"]


@runtime_checkable
class AdapterInterface(CacheItemPoolInterface, CacheInterface, Protocol):
    """A pool handing out :class:`~xtr_cache.cache_item.CacheItem`, with fetch-or-compute on top.

    Every adapter of this library is one, which is what lets them wrap and
    chain each other: an item one hands out, another stores.
    """

    @override
    async def get_item(self, key: str, /) -> CacheItem:
        """Return the item for ``key``, a hit or a miss."""
        ...

    @override
    async def get_items(self, keys: Iterable[str], /) -> Mapping[str, CacheItem]:
        """Return an item for each of ``keys``, in the order asked."""
        ...

    async def reset(self) -> None:
        """End a unit of work: store what was saved as deferred, and forget per-unit state.

        What a long-running process calls between messages or requests, so
        deferred items do not wait for a commit that nothing will call.
        """
        ...
