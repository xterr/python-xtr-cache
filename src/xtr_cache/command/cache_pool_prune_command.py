"""``cache:pool:prune``: remove expired values from the pools that keep them."""

from __future__ import annotations

from typing import final

from xtr_console import ConsoleStyle, ExitCode, as_command, escape

from xtr_cache.pruneable_interface import PruneableInterface

from .pool_command import PoolCommand

__all__ = ["CachePoolPruneCommand"]


@as_command("cache:pool:prune")
@final
class CachePoolPruneCommand(PoolCommand):
    """Prunes cache pools: removes the expired values their backend keeps."""

    __slots__ = ()

    async def __call__(self, io: ConsoleStyle) -> int:
        """Prune cache pools.

        Args:
            io: Where the command writes.
        """
        clearer = self._pools_or_report(io)
        if clearer is None:
            return ExitCode.FAILURE

        failed: list[str] = []
        for name in clearer.pool_names():
            cache = await clearer.get_pool(name)
            if not isinstance(cache, PruneableInterface):
                continue
            io.text(f"Pruning cache pool: {escape(name)}")
            if not await cache.prune():
                failed.append(name)

        if failed:
            io.error(f"Could not prune: {escape(', '.join(failed))}.")
            return ExitCode.FAILURE

        io.success("Successfully pruned cache pool(s).")
        return ExitCode.SUCCESS
