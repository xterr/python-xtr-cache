"""How one cache pool is built."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TypeAlias

from xtr_dependency_injection import Reference, one_or_many

from xtr_cache.cache_item import CacheItem
from xtr_cache.exception import InvalidArgumentError

__all__ = ["AdapterEntry", "PoolConfig"]

AdapterEntry: TypeAlias = str | Reference
"""One adapter: a DSN or keyword :class:`~xtr_cache.adapter.AdapterFactory` reads, or a client."""


@dataclass(frozen=True, slots=True)
class PoolConfig:
    """One pool: its adapter, how long its values live, and whether it takes tags.

    ```python
    PoolConfig(adapter=["array", "redis://cache:6379"], default_lifetime=600, tags=True)
    PoolConfig(adapter="redis://cache:6379", tags="tag_versions")  # versions in another pool
    ```

    Attributes:
        adapter: The adapter, or several to chain, fastest first. ``None``
            uses the application pool's.
        default_lifetime: Seconds a value lives when its item sets no expiry;
            ``0`` for no limit.
        tags: Whether items can be tagged and invalidated by tag — ``True``
            keeping tag versions in the pool itself, or the name of another
            pool to keep them in, a faster or wider-shared one.
        namespace: What every key is put under. ``None`` derives one from the
            pool's name and the configuration's prefix seed, so pools sharing
            a backend never see each other's keys.
    """

    adapter: AdapterEntry | Sequence[AdapterEntry] | None = None
    default_lifetime: float = 0.0
    tags: bool | str = False
    namespace: str | None = None

    def __post_init__(self) -> None:
        """Refuse an adapter that is neither a string nor a reference, or a negative lifetime.

        Raises:
            InvalidArgumentError: When the configuration cannot be read.
        """
        if self.adapter is not None:
            for entry in one_or_many(self.adapter):
                if not isinstance(entry, (str, Reference)):  # pyright: ignore[reportUnnecessaryIsInstance] -- configs are written by hand; the annotation is not enforced
                    raise InvalidArgumentError(
                        f'A cache adapter must be a string or a Reference, got "{entry!r}".',
                    )
        if self.default_lifetime < 0:
            raise InvalidArgumentError(
                f"A cache pool's default lifetime must not be negative, "
                f"got {self.default_lifetime}.",
            )
        if self.namespace is not None:
            _ = CacheItem.validate_key(self.namespace)

    def adapters(self) -> tuple[AdapterEntry, ...]:
        """Return the adapters as a tuple; empty when the pool uses the application pool's."""
        return one_or_many(self.adapter) if self.adapter is not None else ()
