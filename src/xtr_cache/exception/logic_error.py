"""An operation was asked of an object that cannot perform it."""

from __future__ import annotations

from xtr_cache_contracts import CacheError

__all__ = ["LogicError"]


class LogicError(CacheError):
    """An operation was asked of an object that cannot perform it.

    Tagging an item that comes from a pool which cannot store tags, say. A
    mistake in the calling code, never a backend failing.

    Attributes:
        reason: What was asked, and why it cannot be done.
    """

    reason: str

    def __init__(self, reason: str) -> None:
        """Record what was asked, and why it cannot be done."""
        self.reason = reason
        super().__init__(reason)
