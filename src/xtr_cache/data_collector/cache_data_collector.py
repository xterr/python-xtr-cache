"""Every cache pool call the request made, and what they added up to."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, final

from ._masking import masked_key

if TYPE_CHECKING:
    from collections.abc import Iterable

    from xtr_http_kernel.data_collector import ProfiledRequest, RequestTrace

    from .cache_call import CacheCall

__all__ = ["CacheDataCollector"]

_NAME: Final = "cache"
_READS: Final = frozenset({"get", "get_item", "get_items", "has_item"})
_WRITES: Final = frozenset({"save", "save_deferred", "commit"})
_DELETES: Final = frozenset({"delete", "delete_item", "delete_items", "clear", "invalidate_tags"})


@final
class CacheDataCollector:
    """Keeps the calls the request's traced pools recorded, in the order they were made.

    The pools record into a trace of the request being served, which
    :meth:`begin_request` starts as a profiled request arrives; the calls are
    read once everything has been sent, so a call made while the body
    streamed is there too. Besides the calls: totals for the request, and the
    same per pool. A key named like a credential — a token, a secret — is
    kept as ``******``.
    """

    __slots__ = ("_trace",)

    def __init__(self, trace: RequestTrace[CacheCall]) -> None:
        """Read the calls the traced pools record into ``trace``."""
        self._trace = trace

    @property
    def name(self) -> str:
        """``"cache"``."""
        return _NAME

    def begin_request(self) -> None:
        """Start recording the calls of the request that just arrived."""
        self._trace.begin()

    def collect(self, profiled: ProfiledRequest) -> dict[str, object]:
        """Return the calls made so far; the rest follow once the response has left."""
        del profiled
        return self._read()

    def late_collect(self, data: dict[str, object], profiled: ProfiledRequest) -> dict[str, object]:
        """Return every call of the request."""
        del data, profiled
        return self._read()

    def _read(self) -> dict[str, object]:
        calls = self._trace.entries()
        pools = dict.fromkeys(call.pool for call in calls)
        return {
            "calls": [
                {
                    "pool": call.pool,
                    "method": call.method,
                    "keys": [masked_key(key) for key in call.keys],
                    "hits": call.hits,
                    "misses": call.misses,
                    "duration_ms": call.duration_ms,
                    "result": call.result,
                }
                for call in calls
            ],
            "totals": _totals(calls),
            "pools": {pool: _totals(call for call in calls if call.pool == pool) for pool in pools},
        }


def _totals(calls: Iterable[CacheCall]) -> dict[str, object]:
    kept = list(calls)
    return {
        "calls": len(kept),
        "reads": sum(1 for call in kept if call.method in _READS),
        "hits": sum(call.hits for call in kept),
        "misses": sum(call.misses for call in kept),
        "writes": sum(1 for call in kept if call.method in _WRITES),
        "deletes": sum(1 for call in kept if call.method in _DELETES),
        "duration_ms": round(sum((call.duration_ms for call in kept), 0.0), 3),
    }
