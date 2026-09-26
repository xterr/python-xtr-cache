"""A cached value stored together with its metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, final

if TYPE_CHECKING:
    from xtr_cache_contracts import Metadata

__all__ = ["ValueWrapper"]


@final
@dataclass(frozen=True, slots=True)
class ValueWrapper:
    """What a pool stores when a value carries metadata: the value, and the metadata.

    Values stored without metadata are stored as they are, so this wrapper
    costs nothing to a pool that never records any. It is part of the stored
    format: its module and name must not change, or values already stored
    would no longer be read back.

    Attributes:
        value: The cached value.
        metadata: Its expiry, how long it took to compute, its tags.
    """

    value: object
    metadata: Metadata
