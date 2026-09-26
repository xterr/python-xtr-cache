"""The pools: in memory, in files, in Redis, nowhere, chained, or tag-aware."""

from __future__ import annotations

from .abstract_adapter import AbstractAdapter
from .adapter_factory import AdapterFactory
from .adapter_interface import AdapterInterface
from .array_adapter import ArrayAdapter
from .chain_adapter import ChainAdapter
from .contracts_mixin import ContractsMixin
from .filesystem_adapter import FilesystemAdapter
from .null_adapter import NullAdapter
from .redis_adapter import RedisAdapter
from .tag_aware_adapter import TagAwareAdapter
from .tag_aware_adapter_interface import TagAwareAdapterInterface
from .tagged_value import TaggedValue

__all__ = [
    "AbstractAdapter",
    "AdapterFactory",
    "AdapterInterface",
    "ArrayAdapter",
    "ChainAdapter",
    "ContractsMixin",
    "FilesystemAdapter",
    "NullAdapter",
    "RedisAdapter",
    "TagAwareAdapter",
    "TagAwareAdapterInterface",
    "TaggedValue",
]
