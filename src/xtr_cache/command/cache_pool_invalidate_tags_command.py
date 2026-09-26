"""``cache:pool:invalidate-tags``: drop every value carrying a tag."""

from __future__ import annotations

from typing import Annotated, final

from xtr_cache_contracts import InvalidArgumentError, TagAwareCacheInterface
from xtr_console import ConsoleStyle, ExitCode, Option, as_command, escape

from xtr_cache.cache_pool_clearer import CachePoolClearer

from .pool_command import PoolCommand

__all__ = ["CachePoolInvalidateTagsCommand"]


@as_command("cache:pool:invalidate-tags")
@final
class CachePoolInvalidateTagsCommand(PoolCommand):
    """Invalidates cache tags, in every tag-aware pool or in the ones named."""

    __slots__ = ()

    async def __call__(
        self,
        io: ConsoleStyle,
        *tags: str,
        pool: Annotated[list[str] | None, Option(alias="-p")] = None,
    ) -> int:
        """Invalidate cache tags.

        Args:
            io: Where the command writes.
            tags: The tags to invalidate.
            pool: A pool to invalidate them in; repeat for several. Every
                tag-aware pool when omitted.
        """
        clearer = self._pools_or_report(io)
        if clearer is None:
            return ExitCode.FAILURE
        if not tags:
            io.error("Name at least one tag to invalidate.")
            return ExitCode.INVALID

        names = list(dict.fromkeys(pool)) if pool else list(clearer.pool_names())
        unknown = [name for name in names if not clearer.has_pool(name)]
        if unknown:
            io.error(f'Unknown cache pool "{escape(unknown[0])}".')
            return ExitCode.INVALID

        try:
            invalidated, errors = await _invalidate(io, clearer, names, tags, named=bool(pool))
        except InvalidArgumentError as error:
            io.error(escape(error.reason))
            return ExitCode.INVALID

        if errors:
            io.error("Done, but with errors.")
            return ExitCode.FAILURE
        if invalidated:
            io.success("Successfully invalidated cache tags.")
        else:
            io.note("No tag-aware cache pool to invalidate tags in.")
        return ExitCode.SUCCESS


async def _invalidate(
    io: ConsoleStyle,
    clearer: CachePoolClearer,
    names: list[str],
    tags: tuple[str, ...],
    *,
    named: bool,
) -> tuple[int, bool]:
    """Invalidate ``tags`` in every tag-aware pool of ``names``.

    A pool that is not tag-aware is an error when it was named, and skipped
    when every pool was asked.

    Returns:
        How many pools invalidated them, and whether any failed.
    """
    invalidated = 0
    errors = False
    for name in names:
        cache = await clearer.get_pool(name)
        if not isinstance(cache, TagAwareCacheInterface):
            if named:
                io.error(f'Cache pool "{escape(name)}" is not tag-aware.')
                errors = True
            continue
        if not await cache.invalidate_tags(tags):
            io.error(f'Cache tags could not be invalidated in pool "{escape(name)}".')
            errors = True
            continue
        io.text(f'Invalidated tags in cache pool "{escape(name)}".')
        invalidated += 1

    return invalidated, errors
