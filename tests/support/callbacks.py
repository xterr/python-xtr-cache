"""Callbacks for ``get()``: computing a value, taking time, expiring, and counting calls."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Generic, TypeVar, final

if TYPE_CHECKING:
    from xtr_clock import MockClock

    from xtr_cache import ItemInterface

__all__ = ["Computation"]

_T = TypeVar("_T")


@final
class Computation(Generic[_T]):
    """Computes ``value``, recording each item it was called with.

    ``lifetime`` is set on the item, ``tags`` added to it; ``took`` seconds pass
    on ``clock`` while computing; a computation ``held`` waits for
    :meth:`release` before it returns, and ``fails_with`` makes it raise.
    """

    def __init__(  # noqa: PLR0913 — every option past the value is keyword-only.
        self,
        value: _T,
        *,
        lifetime: float | None = None,
        tags: tuple[str, ...] = (),
        took: float = 0.0,
        clock: MockClock | None = None,
        held: bool = False,
        fails_with: Exception | None = None,
    ) -> None:
        self.value = value
        self.items: list[ItemInterface] = []
        self._lifetime = lifetime
        self._tags = tags
        self._took = took
        self._clock = clock
        self._fails_with = fails_with
        self.started = asyncio.Event()
        self._released = asyncio.Event()
        if not held:
            self._released.set()

    @property
    def calls(self) -> int:
        """How many times it was called."""
        return len(self.items)

    def release(self) -> None:
        """Let a held computation return."""
        self._released.set()

    async def __call__(self, item: ItemInterface) -> _T:
        self.items.append(item)
        self.started.set()
        if self._lifetime is not None:
            _ = item.expires_after(self._lifetime)
        if self._tags:
            _ = item.tag(list(self._tags))
        if self._clock is not None and self._took:
            await self._clock.sleep_async(self._took)
        _ = await self._released.wait()
        if self._fails_with is not None:
            raise self._fails_with
        return self.value
