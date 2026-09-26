"""A pool that stores nothing."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from typing_extensions import override
from xtr_cache_contracts import CacheMixin, NamespacedPoolInterface

from xtr_cache.cache_item import CacheItem

from .adapter_interface import AdapterInterface

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from xtr_cache_contracts import ItemInterface

__all__ = ["NullAdapter"]


@final
class NullAdapter(CacheMixin, AdapterInterface, NamespacedPoolInterface):
    """Stores nothing: every read misses, every write succeeds.

    For switching caching off without changing the code that caches:
    :meth:`get` computes every time — every read being a miss — and
    everything else does nothing.
    """

    __slots__ = ()

    @override
    async def get_item(self, key: str, /) -> CacheItem:
        return CacheItem(CacheItem.validate_key(key))

    @override
    async def get_items(self, keys: Iterable[str], /) -> Mapping[str, CacheItem]:
        return {key: CacheItem(CacheItem.validate_key(key)) for key in keys}

    @override
    async def has_item(self, key: str, /) -> bool:
        _ = CacheItem.validate_key(key)
        return False

    @override
    async def clear(self, prefix: str = "") -> bool:
        return True

    @override
    async def delete_item(self, key: str, /) -> bool:
        _ = CacheItem.validate_key(key)
        return True

    @override
    async def delete_items(self, keys: Iterable[str], /) -> bool:
        for key in keys:
            _ = CacheItem.validate_key(key)
        return True

    @override
    async def save(self, item: ItemInterface, /) -> bool:
        return True

    @override
    async def save_deferred(self, item: ItemInterface, /) -> bool:
        return True

    @override
    async def commit(self) -> bool:
        return True

    @override
    async def reset(self) -> None:
        return None

    @override
    def with_sub_namespace(self, namespace: str, /) -> Self:
        _ = CacheItem.validate_key(namespace)
        return self

    @override
    def __repr__(self) -> str:
        return f"{type(self).__name__}()"
