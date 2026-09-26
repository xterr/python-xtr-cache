"""Cache pools in memory, in files, in Redis, chained or tag-aware.

Every pool implements the ``xtr-cache-contracts`` interfaces, which this
package re-exports rather than redefines — ``xtr_cache.CacheInterface is
xtr_cache_contracts.CacheInterface`` — so code written against the contract
receives these pools unchanged.

```python
cache = FilesystemAdapter("app")


async def load_profile(item: ItemInterface) -> Profile:
    item.expires_after(3600)
    return await profiles.fetch(user_id)


profile = await cache.get(f"profile.{user_id}", load_profile)
```

Every call that reaches a backend is awaited. A backend failing never raises:
reads miss, writes return ``False``, and the pool logs why.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from xtr_cache_contracts import (
    RESERVED_CHARACTERS,
    CacheInterface,
    CacheItemPoolInterface,
    CacheMixin,
    Callback,
    ItemInterface,
    Metadata,
    NamespacedPoolInterface,
    TagAwareCacheInterface,
)

from .adapter import (
    AbstractAdapter,
    AdapterFactory,
    AdapterInterface,
    ArrayAdapter,
    ChainAdapter,
    ContractsMixin,
    FilesystemAdapter,
    NullAdapter,
    RedisAdapter,
    TagAwareAdapter,
    TagAwareAdapterInterface,
    TaggedValue,
)
from .cache_item import CacheItem
from .cache_pool_clearer import CachePoolClearer, PoolProvider
from .exception import CacheError, InvalidArgumentError, LogicError, MarshallingError
from .lock_registry import LockRegistry
from .marshaller import (
    DefaultMarshaller,
    DeflateMarshaller,
    MarshallerInterface,
    SodiumMarshaller,
)
from .pruneable_interface import PruneableInterface
from .value_wrapper import ValueWrapper

try:
    __version__ = version("xtr-cache")
except PackageNotFoundError:  # pragma: no cover
    # Running from a source tree or a vendored copy, with no installed
    # metadata to read. Having no version is better than refusing to import.
    __version__ = "0+unknown"

__all__ = [
    "RESERVED_CHARACTERS",
    "AbstractAdapter",
    "AdapterFactory",
    "AdapterInterface",
    "ArrayAdapter",
    "CacheError",
    "CacheInterface",
    "CacheItem",
    "CacheItemPoolInterface",
    "CacheMixin",
    "CachePoolClearer",
    "Callback",
    "ChainAdapter",
    "ContractsMixin",
    "DefaultMarshaller",
    "DeflateMarshaller",
    "FilesystemAdapter",
    "InvalidArgumentError",
    "ItemInterface",
    "LockRegistry",
    "LogicError",
    "MarshallerInterface",
    "MarshallingError",
    "Metadata",
    "NamespacedPoolInterface",
    "NullAdapter",
    "PoolProvider",
    "PruneableInterface",
    "RedisAdapter",
    "SodiumMarshaller",
    "TagAwareAdapter",
    "TagAwareAdapterInterface",
    "TagAwareCacheInterface",
    "TaggedValue",
    "ValueWrapper",
    "__version__",
]
