"""``cache:pool:delete``: remove one key from a pool."""

from __future__ import annotations

from typing import final

from xtr_cache_contracts import InvalidArgumentError
from xtr_console import ConsoleStyle, ExitCode, as_command, escape

from .pool_command import PoolCommand

__all__ = ["CachePoolDeleteCommand"]


@as_command("cache:pool:delete")
@final
class CachePoolDeleteCommand(PoolCommand):
    """Deletes an item from a cache pool."""

    __slots__ = ()

    async def __call__(self, io: ConsoleStyle, pool: str, key: str) -> int:
        """Delete an item from a cache pool.

        Args:
            io: Where the command writes.
            pool: The pool, by name.
            key: The key of the item to delete.
        """
        clearer = self._pools_or_report(io)
        if clearer is None:
            return ExitCode.FAILURE

        try:
            cache = await clearer.get_pool(pool)
            exists = await cache.has_item(key)
        except InvalidArgumentError as error:
            io.error(escape(error.reason))
            return ExitCode.INVALID

        if not exists:
            io.note(f'Cache item "{escape(key)}" does not exist in cache pool "{escape(pool)}".')
            return ExitCode.SUCCESS

        if not await cache.delete_item(key):
            io.error(f'Cache item "{escape(key)}" could not be deleted.')
            return ExitCode.FAILURE

        io.success(f'Cache item "{escape(key)}" was successfully deleted.')
        return ExitCode.SUCCESS
