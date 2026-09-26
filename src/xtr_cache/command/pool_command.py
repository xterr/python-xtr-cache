"""What every cache command shares: where the pools come from."""

from __future__ import annotations

from typing import ClassVar

from xtr_console import ConsoleStyle

from xtr_cache.cache_pool_clearer import CachePoolClearer

from .pools import NO_POOLS, UNSET, resolve_pools

__all__ = ["PoolCommand"]


class PoolCommand:
    """A cache command, acting on the pools a container gives it — or ``use_pools()`` does.

    A container builds each command with the pools its bundle registered;
    without one, the console builds it bare, and it falls back to the pools
    set with :func:`~xtr_cache.command.pools.use_pools`.
    """

    __slots__: ClassVar[tuple[str, ...]] = ("_pools",)

    _pools: CachePoolClearer

    def __init__(self, pools: CachePoolClearer = UNSET) -> None:
        """Act on ``pools``, or on those set with ``use_pools()`` when omitted."""
        self._pools = pools

    def _pools_or_report(self, io: ConsoleStyle) -> CachePoolClearer | None:
        """Return the pools to act on, or report on ``io`` that there are none."""
        pools = resolve_pools(self._pools)
        if pools is None:
            io.error(NO_POOLS)
        return pools
