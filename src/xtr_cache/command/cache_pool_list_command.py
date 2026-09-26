"""``cache:pool:list``: name every pool."""

from __future__ import annotations

from typing import final

from xtr_console import ConsoleStyle, ExitCode, as_command, escape

from .pool_command import PoolCommand

__all__ = ["CachePoolListCommand"]


@as_command("cache:pool:list")
@final
class CachePoolListCommand(PoolCommand):
    """Lists the available cache pools."""

    __slots__ = ()

    async def __call__(self, io: ConsoleStyle) -> int:
        """List the available cache pools.

        Args:
            io: Where the command writes.
        """
        clearer = self._pools_or_report(io)
        if clearer is None:
            return ExitCode.FAILURE

        io.table(["Pool name"], [[escape(name)] for name in clearer.pool_names()])
        return ExitCode.SUCCESS
