"""A pool that records every call a profiled request makes to it."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, ClassVar, Self, final, override

from xtr_cache_contracts import NamespacedPoolInterface
from xtr_clock import MonotonicClock

from xtr_cache.adapter.adapter_interface import AdapterInterface
from xtr_cache.exception.logic_error import LogicError
from xtr_cache.pruneable_interface import PruneableInterface

from .cache_call import CacheCall

if TYPE_CHECKING:
    from collections.abc import Generator, Iterable, Mapping, Sequence

    from xtr_cache_contracts import Callback, ItemInterface, Metadata
    from xtr_clock import ClockInterface
    from xtr_http_kernel.data_collector import RequestTrace

    from xtr_cache.cache_item import CacheItem

__all__ = ["TraceableAdapter"]


@final
class _PendingCall:
    """What a call found out, filled in while it runs and recorded once it is over."""

    __slots__ = ("hits", "misses", "result")

    def __init__(self) -> None:
        self.hits = 0
        self.misses = 0
        self.result: bool | None = None

    def read(self, hits: int, keys: int) -> None:
        """Count ``hits`` of ``keys`` read as found, the rest as missed."""
        self.hits = hits
        self.misses = keys - hits


class TraceableAdapter(AdapterInterface, NamespacedPoolInterface, PruneableInterface):
    """Hands every call to the pool it wraps, recording it into a request trace.

    Each call becomes a :class:`~xtr_cache.data_collector.CacheCall`: the
    keys, how many were hits, how long it took, what a write returned. The
    trace keeps the calls of the profiled request being served and nothing
    outside one, so a pool shared by every request records each request's
    calls apart — and, outside a profiled request, a call costs one lookup.

    The pool's own work is untouched: a ``get`` computing on a miss saves
    through the wrapped pool, not through this one, so it is one call here.
    Subclassed by :class:`~xtr_cache.data_collector.TraceableTagAwareAdapter`
    for a pool with tags.
    """

    __slots__: ClassVar[tuple[str, ...]] = ("_clock", "_pool", "_pool_name", "_trace")

    _pool: AdapterInterface
    _pool_name: str
    _trace: RequestTrace[CacheCall]
    _clock: ClockInterface

    def __init__(
        self,
        pool: AdapterInterface,
        pool_name: str,
        trace: RequestTrace[CacheCall],
        clock: ClockInterface | None = None,
    ) -> None:
        """Record the calls made to ``pool``, under ``pool_name``, into ``trace``.

        Args:
            pool: The pool every call goes to.
            pool_name: The name the pool is configured under, which each call
                is recorded with.
            trace: Where calls are recorded.
            clock: What durations are measured with; a
                :class:`~xtr_clock.MonotonicClock` by default, so a wall
                clock correction never makes a call look slow or negative.
        """
        self._pool = pool
        self._pool_name = pool_name
        self._trace = trace
        self._clock = clock if clock is not None else MonotonicClock()

    @property
    def pool(self) -> AdapterInterface:
        """The pool every call goes to."""
        return self._pool

    @override
    async def get[T](
        self,
        key: str,
        callback: Callback[T],
        /,
        *,
        beta: float | None = None,
        metadata: Metadata | None = None,
    ) -> T:
        computed = False

        async def compute(item: ItemInterface) -> T:
            nonlocal computed
            computed = True
            return await callback(item)

        with self._recording("get", (key,)) as call:
            try:
                return await self._pool.get(key, compute, beta=beta, metadata=metadata)
            finally:
                call.read(0 if computed else 1, 1)

    @override
    async def delete(self, key: str, /) -> bool:
        with self._recording("delete", (key,)) as call:
            call.result = await self._pool.delete(key)
            return call.result

    @override
    async def get_item(self, key: str, /) -> CacheItem:
        with self._recording("get_item", (key,)) as call:
            item = await self._pool.get_item(key)
            call.read(int(item.is_hit()), 1)
            return item

    @override
    async def get_items(self, keys: Iterable[str], /) -> Mapping[str, CacheItem]:
        wanted = list(keys)
        with self._recording("get_items", wanted) as call:
            items = await self._pool.get_items(wanted)
            call.read(sum(item.is_hit() for item in items.values()), len(items))
            return items

    @override
    async def has_item(self, key: str, /) -> bool:
        with self._recording("has_item", (key,)) as call:
            found = await self._pool.has_item(key)
            call.read(int(found), 1)
            return found

    @override
    async def clear(self, prefix: str = "") -> bool:
        with self._recording("clear", (prefix,) if prefix else ()) as call:
            call.result = await self._pool.clear(prefix)
            return call.result

    @override
    async def delete_item(self, key: str, /) -> bool:
        with self._recording("delete_item", (key,)) as call:
            call.result = await self._pool.delete_item(key)
            return call.result

    @override
    async def delete_items(self, keys: Iterable[str], /) -> bool:
        wanted = list(keys)
        with self._recording("delete_items", wanted) as call:
            call.result = await self._pool.delete_items(wanted)
            return call.result

    @override
    async def save(self, item: ItemInterface, /) -> bool:
        with self._recording("save", (item.key,)) as call:
            call.result = await self._pool.save(item)
            return call.result

    @override
    async def save_deferred(self, item: ItemInterface, /) -> bool:
        with self._recording("save_deferred", (item.key,)) as call:
            call.result = await self._pool.save_deferred(item)
            return call.result

    @override
    async def commit(self) -> bool:
        with self._recording("commit", ()) as call:
            call.result = await self._pool.commit()
            return call.result

    @override
    async def reset(self) -> None:
        with self._recording("reset", ()):
            await self._pool.reset()

    @override
    async def prune(self) -> bool:
        """Prune the wrapped pool; one that keeps no expired value has nothing to prune."""
        pool = self._pool
        if not isinstance(pool, PruneableInterface):
            return True
        with self._recording("prune", ()) as call:
            call.result = await pool.prune()
            return call.result

    @override
    def with_sub_namespace(self, namespace: str, /) -> Self:
        """Return the wrapped pool's view under ``namespace``, traced under the same name.

        Raises:
            LogicError: When the wrapped pool has no sub-namespaces.
        """
        pool = self._pool
        if not isinstance(pool, NamespacedPoolInterface):
            raise LogicError(f"{pool!r} cannot be confined to a sub-namespace.")
        return type(self)(
            pool.with_sub_namespace(namespace), self._pool_name, self._trace, self._clock
        )

    @override
    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._pool!r}, {self._pool_name!r})"

    @contextmanager
    def _recording(self, method: str, keys: Sequence[str]) -> Generator[_PendingCall]:
        """Time the call made inside, and record it — when a profiled request is recorded."""
        call = _PendingCall()
        if not self._trace.is_recording():
            yield call
            return
        started = self._clock.now()
        try:
            yield call
        finally:
            elapsed = self._clock.now() - started
            self._trace.record(
                CacheCall(
                    pool=self._pool_name,
                    method=method,
                    keys=tuple(keys),
                    hits=call.hits,
                    misses=call.misses,
                    duration_ms=round(elapsed.total_seconds() * 1000, 3),
                    result=call.result,
                )
            )
