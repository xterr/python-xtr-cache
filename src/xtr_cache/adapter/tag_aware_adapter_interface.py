"""A pool of this library whose values can be invalidated by tag."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from xtr_cache_contracts import TagAwareCacheInterface

from .adapter_interface import AdapterInterface

__all__ = ["TagAwareAdapterInterface"]


@runtime_checkable
class TagAwareAdapterInterface(AdapterInterface, TagAwareCacheInterface, Protocol):
    """An adapter whose items can be tagged, and invalidated by any of their tags."""
