"""One call a profiled request made to a cache pool."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["CacheCall"]


@dataclass(frozen=True, slots=True)
class CacheCall:
    """What a traced pool records of one call, for the profiler's cache panel.

    Kept as the call left it, values aside: a profile shows what the request
    asked of its caches and what that cost, never what was cached.

    Attributes:
        pool: The name the pool is configured under.
        method: The pool method called — ``get``, ``get_item``, ``save``…
        keys: The keys the call named, in the order given; the tags, for
            ``invalidate_tags``.
        hits: How many of the keys read were found.
        misses: How many of the keys read were not — for ``get``, whether
            the callback had to compute the value.
        duration_ms: How long the call took, in milliseconds.
        result: What a write, a delete or a clear returned; ``None`` for a read.
    """

    pool: str
    method: str
    keys: tuple[str, ...]
    hits: int
    misses: int
    duration_ms: float
    result: bool | None
