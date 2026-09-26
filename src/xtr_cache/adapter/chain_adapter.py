"""Several pools in front of one another, the fastest first."""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Self, final

from typing_extensions import override
from xtr_cache_contracts import InvalidArgumentError, NamespacedPoolInterface

from xtr_cache.cache_item import CacheItem
from xtr_cache.pruneable_interface import PruneableInterface

from .adapter_interface import AdapterInterface
from .contracts_mixin import ContractsMixin

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from xtr_cache_contracts import ItemInterface
    from xtr_clock import ClockInterface

__all__ = ["ChainAdapter"]


@final
class ChainAdapter(ContractsMixin, AdapterInterface, NamespacedPoolInterface, PruneableInterface):
    """Reads from the first pool that has a value, and fills the faster ones with it.

    Typically memory in front of Redis: a hit in memory costs nothing, a miss
    there asks Redis, and a value found in Redis is copied into memory for
    the next read — with what is left of its lifetime, when it was stored
    with one, or ``default_lifetime`` otherwise. Writes, deletes and clears
    go to every pool.
    """

    _adapters: tuple[AdapterInterface, ...]
    _default_lifetime: float

    def __init__(
        self,
        adapters: Sequence[AdapterInterface],
        default_lifetime: float = 0.0,
        *,
        clock: ClockInterface | None = None,
    ) -> None:
        """Chain ``adapters``, the fastest first.

        Args:
            adapters: The pools, in the order they are read.
            default_lifetime: Seconds a value copied into a faster pool lives,
                when it was stored without an expiry; ``0`` leaves it to that
                pool's own default.
            clock: What lifetimes are counted from. ``None`` reads the clock
                in force.

        Raises:
            InvalidArgumentError: When ``adapters`` is empty.
        """
        if not adapters:
            raise InvalidArgumentError("A chain needs at least one cache pool.")

        self._adapters = tuple(adapters)
        self._default_lifetime = default_lifetime
        if clock is not None:
            self._clock = clock

    @property
    def adapters(self) -> tuple[AdapterInterface, ...]:
        """The pools, in the order they are read."""
        return self._adapters

    @override
    async def get_item(self, key: str, /) -> CacheItem:
        missed: list[AdapterInterface] = []
        for adapter in self._adapters:
            item = await adapter.get_item(key)
            if item.is_hit():
                for faster in missed:
                    _ = await faster.save(self._copy(item))
                return item
            missed.append(adapter)

        return CacheItem(key, clock=self._clock)

    @override
    async def get_items(self, keys: Iterable[str], /) -> Mapping[str, CacheItem]:
        wanted = list(dict.fromkeys(keys))
        found: dict[str, CacheItem] = {}
        missing = wanted
        missed: list[AdapterInterface] = []
        for adapter in self._adapters:
            if not missing:
                break
            items = await adapter.get_items(missing)
            for key, item in items.items():
                if item.is_hit():
                    found[key] = item
                    for faster in missed:
                        _ = await faster.save_deferred(self._copy(item))
            missing = [key for key in missing if key not in found]
            missed.append(adapter)

        for faster in missed:
            _ = await faster.commit()

        return {key: found.get(key) or CacheItem(key, clock=self._clock) for key in wanted}

    @override
    async def has_item(self, key: str, /) -> bool:
        for adapter in self._adapters:
            if await adapter.has_item(key):
                return True
        return False

    @override
    async def clear(self, prefix: str = "") -> bool:
        return all([await adapter.clear(prefix) for adapter in self._adapters])

    @override
    async def delete_item(self, key: str, /) -> bool:
        return all([await adapter.delete_item(key) for adapter in self._adapters])

    @override
    async def delete_items(self, keys: Iterable[str], /) -> bool:
        wanted = list(keys)
        return all([await adapter.delete_items(wanted) for adapter in self._adapters])

    @override
    async def save(self, item: ItemInterface, /) -> bool:
        return all([await adapter.save(item) for adapter in self._adapters])

    @override
    async def save_deferred(self, item: ItemInterface, /) -> bool:
        return all([await adapter.save_deferred(item) for adapter in self._adapters])

    @override
    async def commit(self) -> bool:
        return all([await adapter.commit() for adapter in self._adapters])

    @override
    async def prune(self) -> bool:
        return all(
            [
                await adapter.prune()
                for adapter in self._adapters
                if isinstance(adapter, PruneableInterface)
            ],
        )

    @override
    async def reset(self) -> None:
        for adapter in self._adapters:
            await adapter.reset()

    @override
    def with_sub_namespace(self, namespace: str, /) -> Self:
        clone = copy.copy(self)
        clone._adapters = tuple(  # noqa: SLF001 — a copy of this very class.
            adapter.with_sub_namespace(namespace)
            if isinstance(adapter, NamespacedPoolInterface)
            else adapter
            for adapter in self._adapters
        )
        return clone

    @override
    def _scope(self) -> str:
        first = self._adapters[0]
        return first._scope() if isinstance(first, ContractsMixin) else ""  # noqa: SLF001 — a pool of this library.

    @override
    def __repr__(self) -> str:
        return f"{type(self).__name__}({list(self._adapters)!r}, {self._default_lifetime!r})"

    def _copy(self, item: CacheItem) -> CacheItem:
        """Return an item taking ``item``'s value into a faster pool, with the life it has left."""
        carried = CacheItem(item.key, item.get(), clock=self._clock).carry_metadata(item.metadata)
        expiry = item.metadata.get("expiry")
        if expiry is not None:
            return carried.expires_at(datetime.fromtimestamp(expiry, UTC))
        if self._default_lifetime:
            return carried.expires_after(self._default_lifetime)
        return carried
