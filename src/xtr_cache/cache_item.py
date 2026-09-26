"""The item every pool of this library hands out."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Final, Self, final

from typing_extensions import override
from xtr_cache_contracts import RESERVED_CHARACTERS, InvalidArgumentError, ItemInterface, Metadata
from xtr_clock import Clock

from .exception.logic_error import LogicError
from .value_wrapper import ValueWrapper

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

    from xtr_clock import ClockInterface

__all__ = ["CacheItem"]

_CLOCK_IN_FORCE: Final = Clock()
"""Reads whichever clock is in force when asked, so a frozen test clock reaches every item."""


@final
class CacheItem(ItemInterface):
    """A cache entry: its key, its value when there is one, and how long it should live.

    Pools build items; code that caches receives them from ``get_item`` or in
    a callback, changes them, and hands them back to be saved. Every pool of
    this library stores any :class:`CacheItem`, so an item read from one pool
    can be saved into another — which is how a chain fills its faster levels.

    Beyond the item contract, a few members are for pools and adapters:
    :attr:`expiry`, :attr:`pending_tags`, :meth:`record_computation`,
    :meth:`carry_metadata`, :meth:`pack` and :meth:`from_stored`.
    """

    __slots__ = (
        "_clock",
        "_expiry",
        "_hit",
        "_key",
        "_metadata",
        "_new_metadata",
        "_taggable",
        "_value",
    )

    _key: str
    _value: object
    _hit: bool
    _metadata: Metadata
    _new_metadata: Metadata
    _expiry: float | None
    _taggable: bool
    _clock: ClockInterface

    def __init__(  # noqa: PLR0913 — every option past the value is keyword-only.
        self,
        key: str,
        value: object = None,
        *,
        hit: bool = False,
        metadata: Metadata | None = None,
        taggable: bool = False,
        clock: ClockInterface | None = None,
    ) -> None:
        """Build the item for ``key``.

        Args:
            key: The key, already validated by the pool.
            value: The value found, when ``hit``.
            hit: Whether the pool had a value for the key.
            metadata: What the pool stored alongside the value.
            taggable: Whether the pool it belongs to can store tags.
            clock: What :meth:`expires_after` counts from. ``None`` reads the
                clock in force.
        """
        self._key = key
        self._value = value
        self._hit = hit
        self._metadata = metadata if metadata is not None else Metadata()
        self._new_metadata = Metadata()
        self._expiry = None
        self._taggable = taggable
        self._clock = clock if clock is not None else _CLOCK_IN_FORCE

    @classmethod
    def from_stored(
        cls,
        key: str,
        stored: object,
        *,
        taggable: bool = False,
        clock: ClockInterface | None = None,
    ) -> CacheItem:
        """Build the hit for ``key`` from what a backend returned, unwrapping its metadata."""
        if isinstance(stored, ValueWrapper):
            return cls(
                key,
                stored.value,
                hit=True,
                metadata=stored.metadata.copy(),
                taggable=taggable,
                clock=clock,
            )

        return cls(key, stored, hit=True, taggable=taggable, clock=clock)

    @staticmethod
    def validate_key(key: object) -> str:
        """Return ``key`` when it is a valid key or tag.

        Raises:
            InvalidArgumentError: When ``key`` is not a string, is empty, or
                holds one of :data:`~xtr_cache_contracts.RESERVED_CHARACTERS`.
        """
        if not isinstance(key, str):
            raise InvalidArgumentError(
                f"A cache key must be a string, {type(key).__qualname__} given.",
            )
        if not key:
            raise InvalidArgumentError("A cache key must not be empty.")
        if any(character in RESERVED_CHARACTERS for character in key):
            raise InvalidArgumentError(
                f'Cache key "{key}" contains one of the reserved characters '
                f'"{RESERVED_CHARACTERS}".',
            )

        return key

    @property
    @override
    def key(self) -> str:
        return self._key

    @property
    def expiry(self) -> float | None:
        """When the item expires, as a Unix timestamp; ``None`` for the pool's default lifetime.

        Set by :meth:`expires_at` or :meth:`expires_after`. An item read from a
        pool starts at ``None`` whatever it was stored with: the stored expiry
        is in :attr:`metadata`, and saving the item again starts its lifetime
        over.
        """
        return self._expiry

    @property
    def pending_tags(self) -> tuple[str, ...]:
        """The tags added since the item was read, in the order they were added."""
        return tuple(self._new_metadata.get("tags", ()))

    @property
    def taggable(self) -> bool:
        """Whether the pool this item belongs to can store tags."""
        return self._taggable

    @override
    def get(self) -> object:
        return self._value

    @override
    def is_hit(self) -> bool:
        return self._hit

    @override
    def set(self, value: object, /) -> Self:
        self._value = value
        return self

    @override
    def expires_at(self, expiration: datetime | None, /) -> Self:
        self._expiry = None if expiration is None else expiration.timestamp()
        return self

    @override
    def expires_after(self, ttl: float | timedelta | None, /) -> Self:
        if ttl is None:
            self._expiry = None
            return self

        seconds = ttl.total_seconds() if isinstance(ttl, timedelta) else float(ttl)
        self._expiry = self._clock.now().timestamp() + seconds
        return self

    @override
    def tag(self, tags: str | Iterable[str], /) -> Self:
        """Add one tag, or several.

        Raises:
            LogicError: When the item comes from a pool that cannot store tags.
            InvalidArgumentError: When a tag is not a valid key.
        """
        if not self._taggable:
            raise LogicError(
                f'Cache item "{self._key}" comes from a pool that cannot store tags: '
                f"it cannot be tagged.",
            )

        added = list(self._new_metadata.get("tags", ()))
        for tag in [tags] if isinstance(tags, str) else tags:
            if CacheItem.validate_key(tag) not in added:
                added.append(tag)
        self._new_metadata["tags"] = tuple(added)

        return self

    @property
    @override
    def metadata(self) -> Metadata:
        return self._metadata

    def record_computation(self, ctime: int) -> Self:
        """Remember that the value took ``ctime`` milliseconds, so it can be refreshed early.

        Stored with the value on the next save, together with when it expires —
        the two facts early recomputation needs.
        """
        self._new_metadata["ctime"] = ctime
        return self

    def carry_metadata(self, metadata: Metadata) -> Self:
        """Store ``metadata``'s computation time and tags with the value on the next save.

        What a chain calls on the item it copies into a faster level, so the
        copy keeps what the original was stored with.
        """
        if "ctime" in metadata:
            self._new_metadata["ctime"] = metadata["ctime"]
        if "tags" in metadata:
            self._new_metadata["tags"] = tuple(metadata["tags"])
        return self

    def pack(self, default_expiry: float | None = None) -> object:
        """Return what a backend should store: the value, wrapped with its metadata when it has any.

        The expiry stored is the one that applies: the item's own, or
        ``default_expiry`` — the pool's default lifetime from now — when it set
        none. Storing it is what lets a chain copy the value into a faster pool
        for exactly the life it has left, and early recomputation know when the
        value runs out.

        Args:
            default_expiry: When the value expires if the item set no expiry,
                as a Unix timestamp; ``None`` when it then never expires.
        """
        metadata = self._new_metadata.copy()
        expiry = self._expiry if self._expiry is not None else default_expiry
        if expiry is not None:
            metadata["expiry"] = expiry
        if not metadata:
            return self._value

        return ValueWrapper(self._value, metadata)

    @override
    def __repr__(self) -> str:
        state = "hit" if self._hit else "miss"
        return f"{type(self).__name__}({self._key!r}, {state})"
