"""The named pools an application has, reachable by name."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, TypeAlias, final

from typing_extensions import override
from xtr_cache_contracts import CacheItemPoolInterface, InvalidArgumentError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Mapping

__all__ = ["CachePoolClearer", "PoolProvider"]

PoolProvider: TypeAlias = CacheItemPoolInterface | Callable[[], "Awaitable[CacheItemPoolInterface]"]
"""A pool, or what builds it when first asked for."""


@final
class CachePoolClearer:
    """Knows every named pool, and clears them by name.

    What the ``cache:pool:*`` commands work through. A pool may be given
    built, or as an async function building it, so naming a pool costs
    nothing until a command uses it.
    """

    __slots__ = ("_built", "_pools")

    _pools: dict[str, PoolProvider]
    _built: dict[str, CacheItemPoolInterface]

    def __init__(self, pools: Mapping[str, PoolProvider] | None = None) -> None:
        """Know ``pools`` by name."""
        self._pools = dict(pools or {})
        self._built = {}

    def has_pool(self, name: str) -> bool:
        """Tell whether a pool is known by ``name``."""
        return name in self._pools

    def pool_names(self) -> tuple[str, ...]:
        """Return every pool's name, sorted."""
        return tuple(sorted(self._pools))

    async def get_pool(self, name: str) -> CacheItemPoolInterface:
        """Return the pool known by ``name``, building it the first time.

        Raises:
            InvalidArgumentError: When no pool is known by ``name``.
        """
        built = self._built.get(name)
        if built is not None:
            return built

        provider = self._pools.get(name)
        if provider is None:
            raise InvalidArgumentError(f'Cache pool "{name}" not found.')

        pool = provider if isinstance(provider, CacheItemPoolInterface) else await provider()
        self._built[name] = pool
        return pool

    async def clear_pool(self, name: str, prefix: str = "") -> bool:
        """Clear the pool known by ``name``, or its keys starting with ``prefix``.

        Raises:
            InvalidArgumentError: When no pool is known by ``name``.
        """
        return await (await self.get_pool(name)).clear(prefix)

    async def clear(self, prefix: str = "") -> bool:
        """Clear every pool, or their keys starting with ``prefix``."""
        return all([await self.clear_pool(name, prefix) for name in self.pool_names()])

    @override
    def __repr__(self) -> str:
        return f"{type(self).__name__}({list(self.pool_names())!r})"
