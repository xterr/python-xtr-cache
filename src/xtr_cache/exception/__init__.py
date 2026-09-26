"""Every error this library raises, all deriving from the contract's :class:`CacheError`.

:class:`CacheError` and :class:`InvalidArgumentError` are the contract's own,
re-exported so a caller catching them from here catches exactly what a
library written against ``xtr-cache-contracts`` catches.
"""

from __future__ import annotations

from xtr_cache_contracts import CacheError, InvalidArgumentError

from .logic_error import LogicError
from .marshalling_error import MarshallingError

__all__ = [
    "CacheError",
    "InvalidArgumentError",
    "LogicError",
    "MarshallingError",
]
