"""Configuration for :class:`~xtr_cache.bundle.cache_bundle.CacheBundle`."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, TypeAlias

from xtr_dependency_injection import one_or_many

from xtr_cache.exception import InvalidArgumentError

from .pool_config import AdapterEntry, PoolConfig

__all__ = ["APP_POOL", "CacheConfig", "PoolEntry"]

APP_POOL: Final = "app"
"""The application's own pool, provided without a qualifier too."""

PoolEntry: TypeAlias = AdapterEntry | Sequence[AdapterEntry] | PoolConfig
"""A pool: its adapter, several to chain, or a :class:`PoolConfig`."""


def _no_pools() -> dict[str, PoolEntry]:
    return {}


@dataclass(frozen=True, slots=True)
class CacheConfig:
    """Which cache pools exist, and what each keeps its values in.

    The ``app`` pool always exists; ``pools`` adds more. Each pool is
    registered under the cache interfaces, qualified by its name, and ``app``
    without a qualifier too. A pool given no adapter uses ``app``'s, under a
    namespace of its own.

    An adapter is one of:

    - ``"filesystem"`` — files in :attr:`directory`;
    - any DSN :meth:`~xtr_cache.adapter.AdapterFactory.create_adapter` reads —
      ``"array"``, ``"null"``, ``"filesystem:///var/cache/app"``,
      ``"redis://host:6379"`` and the like — including ``env(...)``;
    - a :class:`~xtr_dependency_injection.Reference` to a client the container
      provides.

    ```python
    CacheConfig(
        app=env("CACHE_DSN"),
        pools={
            "sessions": "redis://cache:6379/1",
            "catalogue": PoolConfig(adapter=["array", "redis://cache:6379"], tags=True),
            "reports": PoolConfig(default_lifetime=3600),
        },
    )
    ```

    Attributes:
        app: The ``app`` pool's adapter, or several to chain, fastest first.
        pools: Every other pool, by name.
        directory: Where ``"filesystem"`` keeps its files: ``cache`` under the
            kernel's ``share_dir`` by default, a directory of the system's
            temporary one set aside for this project.
        prefix_seed: What every pool's namespace is derived from, with its
            name: the project directory by default, so two applications
            sharing a backend never see each other's keys. Give two
            applications the same seed to have them share values.
        stampede_lock: Where the locks go that let one process at a time
            compute a missing value — any lock DSN: file locks next to the
            cache files by default, ``"redis://…"`` to span machines — or
            ``None`` to protect only within each process.
    """

    app: AdapterEntry | Sequence[AdapterEntry] = "filesystem"
    pools: Mapping[str, PoolEntry] = field(default_factory=_no_pools)
    directory: str = "%kernel.share_dir%/cache"
    prefix_seed: str = "%kernel.project_dir%"
    stampede_lock: str | None = "flock://%kernel.share_dir%/cache/locks"

    def __post_init__(self) -> None:
        """Refuse a pool not named, one named ``app``, a wrong adapter, or an unknown tags pool.

        Raises:
            InvalidArgumentError: When the configuration cannot be read.
        """
        _ = PoolConfig(adapter=self.app)
        for name, entry in self.pools.items():
            if not isinstance(name, str) or not name:  # pyright: ignore[reportUnnecessaryIsInstance] -- configs are written by hand; the annotation is not enforced
                raise InvalidArgumentError(f"A cache pool needs a non-empty name, got {name!r}.")
            if name == APP_POOL:
                raise InvalidArgumentError(
                    f'"{APP_POOL}" is the application pool: set it with the "app" option.',
                )
            if not isinstance(entry, PoolConfig):
                _ = PoolConfig(adapter=entry)
            elif isinstance(entry.tags, str) and entry.tags not in {APP_POOL, *self.pools} - {name}:
                raise InvalidArgumentError(
                    f'The "{name}" cache pool keeps its tags in "{entry.tags}", '
                    f"which is not another pool.",
                )

    def pool_configs(self) -> dict[str, PoolConfig]:
        """Return every pool, ``app`` first, each with its adapters resolved to a tuple."""
        app = one_or_many(self.app)
        configs = {APP_POOL: PoolConfig(adapter=app)}
        for name, entry in self.pools.items():
            pool = entry if isinstance(entry, PoolConfig) else PoolConfig(adapter=entry)
            adapters = app if pool.adapter is None else one_or_many(pool.adapter)
            configs[name] = PoolConfig(
                adapter=adapters,
                default_lifetime=pool.default_lifetime,
                tags=pool.tags,
                namespace=pool.namespace,
            )

        return configs
