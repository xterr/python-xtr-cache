"""A pool with tags that records every call a profiled request makes to it."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, final, override

from xtr_cache.adapter.tag_aware_adapter_interface import TagAwareAdapterInterface

from .traceable_adapter import TraceableAdapter

if TYPE_CHECKING:
    from collections.abc import Iterable

    from xtr_clock import ClockInterface
    from xtr_http_kernel.data_collector import RequestTrace

    from .cache_call import CacheCall

__all__ = ["TraceableTagAwareAdapter"]


@final
class TraceableTagAwareAdapter(TraceableAdapter, TagAwareAdapterInterface):
    """A :class:`~xtr_cache.data_collector.TraceableAdapter` that invalidates by tag too.

    Wrapping a pool with tags in the plain decorator would hide
    :meth:`invalidate_tags`, and with it the pool's place under the tag-aware
    interfaces; this one keeps both, and records an invalidation with the
    tags it named as its keys.
    """

    __slots__: ClassVar[tuple[str, ...]] = ("_tag_aware",)

    def __init__(
        self,
        pool: TagAwareAdapterInterface,
        pool_name: str,
        trace: RequestTrace[CacheCall],
        clock: ClockInterface | None = None,
    ) -> None:
        """Record the calls made to ``pool``, under ``pool_name``, into ``trace``.

        Args:
            pool: The pool with tags every call goes to.
            pool_name: The name the pool is configured under.
            trace: Where calls are recorded.
            clock: What durations are measured with; a monotonic clock by default.
        """
        super().__init__(pool, pool_name, trace, clock)
        self._tag_aware = pool

    @override
    async def invalidate_tags(self, tags: Iterable[str], /) -> bool:
        wanted = list(tags)
        with self._recording("invalidate_tags", wanted) as call:
            call.result = await self._tag_aware.invalidate_tags(wanted)
            return call.result
