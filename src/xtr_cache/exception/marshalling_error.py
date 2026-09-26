"""A stored value could not be turned back into what was cached."""

from __future__ import annotations

from xtr_cache_contracts import CacheError

__all__ = ["MarshallingError"]


class MarshallingError(CacheError):
    """A stored value could not be turned back into what was cached.

    Raised by a marshaller's ``unmarshall`` for bytes that are corrupt, were
    written by something else, or fail their integrity check. A pool reading
    such a value logs it and reports a miss, so the caller computes the value
    again rather than failing.

    Attributes:
        reason: Why the value could not be read.
    """

    reason: str

    def __init__(self, reason: str) -> None:
        """Record why the value could not be read."""
        self.reason = reason
        super().__init__(reason)
