"""``cache:pool:clear``: empty the named pools."""

from __future__ import annotations

from typing import Annotated, final

from xtr_console import ConsoleStyle, ExitCode, Option, as_command, escape

from .pool_command import PoolCommand

__all__ = ["CachePoolClearCommand"]


@as_command("cache:pool:clear")
@final
class CachePoolClearCommand(PoolCommand):
    """Clears cache pools."""

    __slots__ = ()

    async def __call__(
        self,
        io: ConsoleStyle,
        *pools: str,
        all_pools: Annotated[bool, Option(name="--all")] = False,
        exclude: list[str] | None = None,
    ) -> int:
        """Clear cache pools.

        Args:
            io: Where the command writes.
            pools: The pools to clear, by name.
            all_pools: Clear every pool.
            exclude: A pool to leave alone with --all; repeat for several.
        """
        clearer = self._pools_or_report(io)
        if clearer is None:
            return ExitCode.FAILURE

        if all_pools:
            skipped = set(exclude or ())
            names = [name for name in clearer.pool_names() if name not in skipped]
        elif pools:
            names = list(dict.fromkeys(pools))
        else:
            io.error("Name at least one pool to clear, or pass --all.")
            return ExitCode.INVALID

        unknown = [name for name in names if not clearer.has_pool(name)]
        if unknown:
            io.error(f'Unknown cache pool "{escape(unknown[0])}".')
            return ExitCode.INVALID

        failed: list[str] = []
        for name in names:
            io.text(f"Clearing cache pool: {escape(name)}")
            if not await clearer.clear_pool(name):
                failed.append(name)

        if failed:
            io.error(f"Could not clear: {escape(', '.join(failed))}.")
            return ExitCode.FAILURE

        io.success("Cache was successfully cleared.")
        return ExitCode.SUCCESS
