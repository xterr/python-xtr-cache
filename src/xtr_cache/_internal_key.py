"""A key the library forms for itself, exempt from the user-key character rules."""

from __future__ import annotations

from typing import final

__all__ = ["InternalKey"]


@final
class InternalKey(str):
    """A key a pool builds internally, trusted past :meth:`CacheItem.validate_key`.

    A tag-aware pool keeps each tag's version under a key starting with a
    control character, so no user key — none of which may hold one — can ever
    name it. :meth:`~xtr_cache.cache_item.CacheItem.validate_key` refuses those
    characters for every key it is handed, which would refuse the version keys
    too; marking them as this type lets the pool reach its own keys without
    reopening that door to a caller.
    """

    __slots__ = ()
