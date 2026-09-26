"""Where the cache commands find the pools they act on."""

from __future__ import annotations

from typing import ClassVar, Final, final

from xtr_cache.cache_pool_clearer import CachePoolClearer

__all__ = ["NO_POOLS", "UNSET", "resolve_pools", "use_pools"]

UNSET: Final = CachePoolClearer()
"""The default of every command's ``pools`` parameter, meaning "no container gave one".

Typed as what a container fills the parameter with, so the engine still
matches it; ``CachePoolClearer | None`` is a different type and never would be.
"""

NO_POOLS: Final = "No cache pools: wire a container, or call xtr_cache.command.use_pools()."


@final
class _Process:
    """The pools commands use where no container supplies them."""

    pools: ClassVar[CachePoolClearer | None] = None


def use_pools(pools: CachePoolClearer | None) -> None:
    """Have every cache command act on ``pools`` wherever no container supplies them."""
    _Process.pools = pools


def resolve_pools(given: CachePoolClearer) -> CachePoolClearer | None:
    """Return the pools a command was given, or those set with :func:`use_pools`."""
    return given if given is not UNSET else _Process.pools
