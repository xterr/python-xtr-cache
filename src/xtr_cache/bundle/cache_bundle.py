"""The xtr-cache bundle: a pool per configured name, with stampede locks and console commands.

An application listing :class:`CacheBundle` gets every pool of its
:class:`CacheConfig` under :class:`~xtr_cache.adapter.AdapterInterface`,
:class:`~xtr_cache_contracts.CacheInterface`,
:class:`~xtr_cache_contracts.CacheItemPoolInterface` and
:class:`~xtr_cache_contracts.NamespacedPoolInterface` — plus the tag-aware
interfaces for a pool with tags — each qualified by the pool's name, and the
``app`` pool without a qualifier too. When the logging bundle is active, a
``cache`` channel is added and every pool logs there; when the console bundle
is, the ``cache:pool:*`` commands are registered.

Nothing is opened until a pool is first asked for: no directory created, no
server reached. Boot checks the configuration without opening anything, so a
mistake fails the application at startup rather than on its first cache read.
A pool commits what it deferred, and closes a connection it opened, when the
container closes; between messages, the kernel's resetter commits it.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Final, final

from typing_extensions import override
from xtr_cache_contracts import (
    CacheInterface,
    CacheItemPoolInterface,
    NamespacedPoolInterface,
    TagAwareCacheInterface,
)
from xtr_dependency_injection import (
    Bundle,
    ContainerBuilder,
    Reference,
    ServiceConfigurator,
    as_bundle,
    bundle_active,
    named_factory,
    optional_service,
    required_bundle,
)
from xtr_lock import InvalidArgumentError as LockArgumentError
from xtr_lock import LockFactory
from xtr_lock.store import RedisStore, StoreFactory
from xtr_logging_contracts import LoggerAwareInterface, LoggerInterface
from xtr_service_contracts import ContainerInterface

from xtr_cache.adapter.adapter_factory import AdapterFactory
from xtr_cache.adapter.adapter_interface import AdapterInterface
from xtr_cache.adapter.chain_adapter import ChainAdapter
from xtr_cache.adapter.contracts_mixin import ContractsMixin
from xtr_cache.adapter.redis_adapter import RedisAdapter
from xtr_cache.adapter.tag_aware_adapter import TagAwareAdapter
from xtr_cache.adapter.tag_aware_adapter_interface import TagAwareAdapterInterface
from xtr_cache.cache_pool_clearer import CachePoolClearer
from xtr_cache.exception import InvalidArgumentError
from xtr_cache.lock_registry import LockRegistry
from xtr_cache.marshaller.default_marshaller import DefaultMarshaller
from xtr_cache.marshaller.marshaller_interface import MarshallerInterface

from .cache_config import APP_POOL, CacheConfig
from .pool_config import AdapterEntry, PoolConfig

__all__ = ["CACHE_CHANNEL", "CacheBundle"]

CACHE_CHANNEL: Final = "cache"
"""The logging channel pools write to."""

_RESET_TAG: Final = "kernel.reset"
_NAMESPACE_LENGTH: Final = 10

_POOL_INTERFACES: Final[tuple[type, ...]] = (
    CacheInterface,
    CacheItemPoolInterface,
    NamespacedPoolInterface,
)
_TAG_AWARE_INTERFACES: Final[tuple[type, ...]] = (
    TagAwareCacheInterface,
    TagAwareAdapterInterface,
)


@final
@required_bundle("xtr_logging.bundle:LoggingBundle", ignore_on_invalid=True)
@required_bundle("xtr_console.bundle:ConsoleBundle", ignore_on_invalid=True)
@as_bundle("cache", config=CacheConfig)
class CacheBundle(Bundle[CacheConfig]):
    """Turns a :class:`CacheConfig` into a pool per name in the container."""

    @override
    def prepend_extension(self, builder: ContainerBuilder) -> None:
        """When ``logging`` is active, add the ``cache`` channel to its config."""
        if not bundle_active(builder, "logging"):
            return
        # Logging is an optional peer, importable only once it is active.
        from xtr_logging.bundle import LoggingConfig  # noqa: PLC0415

        def add_cache_channel(config: LoggingConfig) -> LoggingConfig:
            return config.with_channels(CACHE_CHANNEL)

        builder.prepend_extension_config(LoggingConfig, add_cache_channel)

    @override
    def load_extension(
        self,
        config: CacheConfig,
        services: ServiceConfigurator,
        builder: ContainerBuilder,
    ) -> None:
        """Register every pool under its name, the marshaller, the lock registry, the commands."""
        _ = services.set(_default_marshaller)
        _ = services.set(_cache_pool_clearer)
        if config.stampede_lock is not None:
            _ = services.set(_lock_registry)

        for name, pool in config.pool_configs().items():
            factory = named_factory(_pool_factory(name), f"cache_pool_{name}")
            _ = services.set(factory, qualifier=name).add_tag(_RESET_TAG, method="reset")
            aliases = _POOL_INTERFACES + (_TAG_AWARE_INTERFACES if pool.tags else ())
            for alias in aliases:
                services.alias(alias, AdapterInterface, alias_qualifier=name, target_qualifier=name)
            if name == APP_POOL:
                for alias in (AdapterInterface, *aliases):
                    services.alias(alias, AdapterInterface, target_qualifier=name)

        if bundle_active(builder, "console"):
            services.load("xtr_cache.command")

    @override
    async def boot(self) -> None:
        """Refuse an adapter no DSN serves, or a connection nobody registered, before any read.

        The configuration is read resolved, so a DSN given as ``env(...)`` is
        read here, and a variable that is not set fails the boot.

        Raises:
            InvalidArgumentError: Naming the pool whose adapter is wrong.
        """
        container = self.container
        if container is None:  # pragma: no cover — the kernel sets this before boot.
            message = "CacheBundle.boot ran without a container"
            raise RuntimeError(message)

        config = await container.get(CacheConfig)
        for name, pool in config.pool_configs().items():
            for entry in pool.adapters():
                _check_adapter(name, entry, container)

        if config.stampede_lock is not None:
            try:
                StoreFactory.validate(config.stampede_lock)
            except LockArgumentError as error:
                raise InvalidArgumentError(f"The cache stampede lock: {error.reason}") from error


def _check_adapter(pool: str, entry: AdapterEntry, container: ContainerInterface) -> None:
    if isinstance(entry, Reference):
        if not entry.exists_in(container):
            raise InvalidArgumentError(
                f'The "{pool}" cache pool uses {entry}, which the container does not provide.',
            )
        return

    try:
        AdapterFactory.validate(entry)
    except InvalidArgumentError as error:
        raise InvalidArgumentError(f'The "{pool}" cache pool: {error.reason}') from error


def _default_marshaller() -> MarshallerInterface:
    """Pickle; an application registering its own ``MarshallerInterface`` replaces it."""
    return DefaultMarshaller()


async def _lock_registry(
    config: CacheConfig,
    container: ContainerInterface,
) -> AsyncIterator[LockRegistry]:
    """Build the lock registry every pool computes under, closing what it opened when done.

    Registered only when the configuration names a stampede lock.
    """
    store = StoreFactory.create_store(config.stampede_lock)
    registry = LockRegistry(LockFactory(store))
    logger = await optional_service(container, LoggerInterface, CACHE_CHANNEL)
    if logger is not None:
        registry.set_logger(logger)

    try:
        yield registry
    finally:
        if isinstance(store, RedisStore):
            await store.aclose()


def _cache_pool_clearer(config: CacheConfig, container: ContainerInterface) -> CachePoolClearer:
    """Name every pool for the commands, each built only when a command first needs it."""
    return CachePoolClearer({name: _provider(container, name) for name in config.pool_configs()})


def _provider(
    container: ContainerInterface,
    name: str,
) -> Callable[[], Awaitable[CacheItemPoolInterface]]:
    async def provide() -> CacheItemPoolInterface:
        return await container.get(AdapterInterface, name)

    return provide


def _pool_factory(
    name: str,
) -> Callable[[CacheConfig, ContainerInterface], AsyncIterator[AdapterInterface]]:
    """Build the factory of the pool called ``name``.

    It injects the configuration rather than closing over it: the container
    hands it a copy with every environment placeholder resolved.
    """

    async def pool(
        config: CacheConfig,
        container: ContainerInterface,
    ) -> AsyncIterator[AdapterInterface]:
        spec = config.pool_configs()[name]
        built = await _build_adapters(name, spec, config, container)
        layers: list[AdapterInterface] = list(built)
        if len(built) > 1:
            layers.append(ChainAdapter(built, spec.default_lifetime))
        if spec.tags:
            tags_pool = (
                await container.get(AdapterInterface, spec.tags)
                if isinstance(spec.tags, str)
                else None
            )
            layers.append(TagAwareAdapter(layers[-1], tags_pool))
        adapter = layers[-1]

        logger = await optional_service(container, LoggerInterface, CACHE_CHANNEL)
        for layer in layers:
            if logger is not None and isinstance(layer, LoggerAwareInterface):
                layer.set_logger(logger)
        registry = await optional_service(container, LockRegistry)
        if registry is not None and isinstance(adapter, ContractsMixin):
            adapter.set_lock_registry(registry)

        try:
            yield adapter
        finally:
            try:
                _ = await adapter.commit()
            finally:
                for each in built:
                    if isinstance(each, RedisAdapter):
                        await each.aclose()

    return pool


async def _build_adapters(
    name: str,
    spec: PoolConfig,
    config: CacheConfig,
    container: ContainerInterface,
) -> list[AdapterInterface]:
    """Build a pool's adapters, fastest first, under the pool's namespace."""
    namespace = (
        spec.namespace if spec.namespace is not None else _namespace(name, config.prefix_seed)
    )
    marshaller = await container.get(MarshallerInterface)

    return [
        AdapterFactory.create_adapter(
            await entry.resolve(container) if isinstance(entry, Reference) else entry,
            namespace,
            spec.default_lifetime,
            marshaller=marshaller,
            directory=config.directory,
        )
        for entry in spec.adapters()
    ]


def _namespace(name: str, seed: str) -> str:
    """Derive a pool's namespace from its name and the seed: short, and a valid key."""
    digest = hashlib.sha256(f"{name}.{seed}".encode()).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii")[:_NAMESPACE_LENGTH]
