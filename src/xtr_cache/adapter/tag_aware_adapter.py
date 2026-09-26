"""Tags on top of any pool, invalidated by version."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, Self, final

from typing_extensions import override
from xtr_cache_contracts import Metadata, NamespacedPoolInterface

from xtr_cache.cache_item import CacheItem
from xtr_cache.pruneable_interface import PruneableInterface
from xtr_cache.value_wrapper import ValueWrapper

from .contracts_mixin import ContractsMixin
from .deferred_items_mixin import DeferredItemsMixin
from .tag_aware_adapter_interface import TagAwareAdapterInterface
from .tagged_value import TaggedValue

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from xtr_clock import ClockInterface

    from .adapter_interface import AdapterInterface

__all__ = ["TagAwareAdapter"]

TAGS_PREFIX: Final = "\x01tags\x01"
"""What the key holding a tag's version starts with, so it never meets a user key."""


@final
class TagAwareAdapter(
    DeferredItemsMixin,
    ContractsMixin,
    TagAwareAdapterInterface,
    NamespacedPoolInterface,
    PruneableInterface,
):
    """Lets items be tagged, and every item carrying a tag be invalidated at once.

    Each tag has a version, kept in the tags pool. An item is saved with the
    versions its tags have at that moment, and is a hit only while every one
    of them still has that version. Invalidating a tag deletes its version:
    every item saved before no longer matches, whatever its key, and the
    next save gives the tag a new one. Nothing is scanned or listed, so
    invalidating costs the same however many items carry the tag.

    Versions are remembered for ``known_tag_versions_ttl`` seconds, so a burst
    of reads asks the tags pool once. Invalidation elsewhere reaches this
    process within that delay. Items saved as deferred take their versions
    when committed, so an invalidation meanwhile does not apply to them.
    """

    _items: AdapterInterface
    _tags: AdapterInterface
    _known_ttl: float
    _known: dict[str, tuple[str | None, float]]
    _deferred: dict[str, CacheItem]

    def __init__(
        self,
        items_pool: AdapterInterface,
        tags_pool: AdapterInterface | None = None,
        known_tag_versions_ttl: float = 0.15,
        *,
        clock: ClockInterface | None = None,
    ) -> None:
        """Tag the items of ``items_pool``, keeping versions in ``tags_pool``.

        Args:
            items_pool: Where values are stored.
            tags_pool: Where tag versions are stored; ``items_pool`` when
                omitted. A faster or shared pool here makes invalidation
                cheaper or wider.
            known_tag_versions_ttl: Seconds a version read from the tags pool
                is trusted before it is read again; ``0`` reads it every time.
            clock: What lifetimes are counted from. ``None`` reads the clock
                in force.
        """
        self._items = items_pool
        self._tags = tags_pool if tags_pool is not None else items_pool
        self._known_ttl = known_tag_versions_ttl
        self._known = {}
        self._deferred = {}
        if clock is not None:
            self._clock = clock

    @override
    async def invalidate_tags(self, tags: Iterable[str], /) -> bool:
        ids: list[str] = []
        for tag in tags:
            ids.append(TAGS_PREFIX + CacheItem.validate_key(tag))
            _ = self._known.pop(tag, None)

        return not ids or await self._tags.delete_items(ids)

    @override
    async def get_item(self, key: str, /) -> CacheItem:
        return (await self.get_items([key]))[key]

    @override
    async def get_items(self, keys: Iterable[str], /) -> Mapping[str, CacheItem]:
        wanted = list(dict.fromkeys(keys))
        await self._commit_if_queued(wanted)

        stored = await self._items.get_items(wanted)
        tags = {
            tag
            for item in stored.values()
            if item.is_hit() and isinstance(value := item.get(), TaggedValue)
            for tag in value.versions
        }
        versions = await self._current_versions(tags)

        return {key: self._outer(key, stored[key], versions) for key in wanted}

    @override
    async def has_item(self, key: str, /) -> bool:
        return (await self.get_item(key)).is_hit()

    @override
    async def clear(self, prefix: str = "") -> bool:
        self._drop_deferred(prefix)
        self._known = {}
        cleared = await self._items.clear(prefix)
        if self._tags is not self._items and not prefix:
            cleared = await self._tags.clear() and cleared
        return cleared

    @override
    async def delete_item(self, key: str, /) -> bool:
        return await self.delete_items([key])

    @override
    async def delete_items(self, keys: Iterable[str], /) -> bool:
        wanted = list(keys)
        self._forget_deferred(wanted)
        return await self._items.delete_items(wanted)

    @override
    async def commit(self) -> bool:
        deferred, self._deferred = self._deferred, {}
        if not deferred:
            return True

        tags = {tag for item in deferred.values() for tag in item.pending_tags}
        versions = await self._versions_for_saving(tags)
        ok = True
        for item in deferred.values():
            ok = await self._items.save_deferred(self._inner(item, versions)) and ok

        return await self._items.commit() and ok

    @override
    async def prune(self) -> bool:
        pools = [self._items] if self._tags is self._items else [self._items, self._tags]
        return all(
            [await pool.prune() for pool in pools if isinstance(pool, PruneableInterface)],
        )

    @override
    async def reset(self) -> None:
        await super().reset()
        self._known = {}
        await self._items.reset()
        if self._tags is not self._items:
            await self._tags.reset()

    @override
    def with_sub_namespace(self, namespace: str, /) -> Self:
        clone = self._unqueued_copy()
        if isinstance(self._items, NamespacedPoolInterface):
            clone._items = self._items.with_sub_namespace(namespace)  # noqa: SLF001 — a copy of this very class.
        return clone

    @override
    def _scope(self) -> str:
        return self._items._scope() if isinstance(self._items, ContractsMixin) else ""  # noqa: SLF001 — a pool of this library.

    @override
    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._items!r}, {self._tags!r})"

    def _outer(self, key: str, inner: CacheItem, versions: Mapping[str, str | None]) -> CacheItem:
        """Return the tag-aware item for what the items pool returned; a miss if a tag moved on."""
        if not inner.is_hit():
            return CacheItem(key, taggable=True, clock=self._clock)

        stored = inner.get()
        if not isinstance(stored, TaggedValue):
            return CacheItem(
                key, stored, hit=True, metadata=inner.metadata, taggable=True, clock=self._clock
            )

        if any(versions.get(tag) != version for tag, version in stored.versions.items()):
            return CacheItem(key, taggable=True, clock=self._clock)

        metadata = inner.metadata.copy()
        if stored.versions:
            metadata["tags"] = tuple(stored.versions)
        return CacheItem(
            key, stored.value, hit=True, metadata=metadata, taggable=True, clock=self._clock
        )

    def _inner(self, item: CacheItem, versions: Mapping[str, str]) -> CacheItem:
        """Return the item the items pool stores for ``item``: its value with its tags' versions."""
        packed = item.pack()
        metadata = packed.metadata if isinstance(packed, ValueWrapper) else Metadata()
        tagged = TaggedValue(item.get(), {tag: versions[tag] for tag in item.pending_tags})
        inner = CacheItem(item.key, tagged, clock=self._clock).carry_metadata(metadata)
        if item.expiry is not None:
            _ = inner.expires_at(datetime.fromtimestamp(item.expiry, UTC))
        return inner

    async def _current_versions(self, tags: Iterable[str]) -> dict[str, str | None]:
        """Return each tag's version, as read or remembered; ``None`` for a tag without one."""
        now = self._clock.now().timestamp()
        versions: dict[str, str | None] = {}
        unknown: list[str] = []
        for tag in tags:
            known = self._known.get(tag)
            if known is not None and known[1] > now:
                versions[tag] = known[0]
            else:
                unknown.append(tag)

        if unknown:
            items = await self._tags.get_items([TAGS_PREFIX + tag for tag in unknown])
            for tag in unknown:
                item = items[TAGS_PREFIX + tag]
                version = item.get() if item.is_hit() else None
                versions[tag] = version if isinstance(version, str) else None
                self._remember(tag, versions[tag], now)

        return versions

    async def _versions_for_saving(self, tags: Iterable[str]) -> dict[str, str]:
        """Return each tag's version, giving a new one to every tag that has none."""
        current = await self._current_versions(tags)
        versions = {tag: found or secrets.token_hex(6) for tag, found in current.items()}
        created = [tag for tag, found in current.items() if found is None]

        for tag in created:
            _ = await self._tags.save_deferred(
                CacheItem(TAGS_PREFIX + tag, versions[tag], clock=self._clock),
            )
        # A version the tags pool did not keep must not be trusted here while others miss it.
        if created and await self._tags.commit():
            now = self._clock.now().timestamp()
            for tag in created:
                self._remember(tag, versions[tag], now)

        return versions

    def _remember(self, tag: str, version: str | None, now: float) -> None:
        """Trust ``version`` for ``tag`` for the next ``known_tag_versions_ttl`` seconds."""
        if self._known_ttl > 0:
            self._known[tag] = (version, now + self._known_ttl)
