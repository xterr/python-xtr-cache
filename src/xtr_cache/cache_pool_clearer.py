"""The named pools an application has, reachable by name."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeAlias, final

from typing_extensions import override
from xtr_cache_contracts import (
    CacheItemPoolInterface,
    InvalidArgumentError,
    TagAwareCacheInterface,
)

from xtr_cache.pruneable_interface import PruneableInterface

if TYPE_CHECKING:
    from collections.abc import Awaitable, Mapping

__all__ = ["CachePoolClearer", "PoolCapabilities", "PoolProvider"]

PoolProvider: TypeAlias = CacheItemPoolInterface | Callable[[], "Awaitable[CacheItemPoolInterface]"]
"""A pool, or what builds it when first asked for."""


@final
@dataclass(frozen=True, slots=True)
class PoolCapabilities:
    """What a pool can do, read from its configuration before it is built.

    A command that acts on only some pools — pruning the ones that keep
    expired values, invalidating tags in the tag-aware ones — asks these of
    every pool and builds only the ones that answer yes, so naming a Redis
    pool it would skip never reaches the server.

    Attributes:
        tag_aware: Whether items can be tagged and invalidated by tag.
        prunable: Whether the backend keeps expired values, so pruning frees
            them.
    """

    tag_aware: bool
    prunable: bool


@final
class CachePoolClearer:
    """Knows every named pool, and clears them by name.

    What the ``cache:pool:*`` commands work through. A pool may be given
    built, or as an async function building it, so naming a pool costs
    nothing until a command uses it.
    """

    __slots__ = ("_built", "_capabilities", "_pools")

    _pools: dict[str, PoolProvider]
    _built: dict[str, CacheItemPoolInterface]
    _capabilities: dict[str, PoolCapabilities]

    def __init__(
        self,
        pools: Mapping[str, PoolProvider] | None = None,
        *,
        capabilities: Mapping[str, PoolCapabilities] | None = None,
    ) -> None:
        """Know ``pools`` by name, with ``capabilities`` a command can read unbuilt.

        A pool given built answers its own capabilities by its type; one given
        as a function to build later needs an entry in ``capabilities``, so a
        command can tell what it does without building it.
        """
        self._pools = dict(pools or {})
        self._built = {}
        self._capabilities = dict(capabilities or {})

    def has_pool(self, name: str) -> bool:
        """Tell whether a pool is known by ``name``."""
        return name in self._pools

    def pool_names(self) -> tuple[str, ...]:
        """Return every pool's name, sorted."""
        return tuple(sorted(self._pools))

    def is_tag_aware(self, name: str) -> bool:
        """Tell whether the pool ``name`` can be invalidated by tag, without building it."""
        capabilities = self._capabilities.get(name)
        if capabilities is not None:
            return capabilities.tag_aware
        return isinstance(self._pools.get(name), TagAwareCacheInterface)

    def is_prunable(self, name: str) -> bool:
        """Tell whether the pool known by ``name`` keeps expired values, without building it."""
        capabilities = self._capabilities.get(name)
        if capabilities is not None:
            return capabilities.prunable
        return isinstance(self._pools.get(name), PruneableInterface)

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
