"""A pool in this process's memory."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast, final

from typing_extensions import override

from xtr_cache.exception import InvalidArgumentError, MarshallingError
from xtr_cache.marshaller.default_marshaller import DefaultMarshaller

from .abstract_adapter import AbstractAdapter

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from xtr_clock import ClockInterface

    from xtr_cache.marshaller.marshaller_interface import MarshallerInterface

__all__ = ["ArrayAdapter"]


@final
class ArrayAdapter(AbstractAdapter):
    """Keeps values in a dictionary, for tests and for caching within one process.

    Values are stored serialized by default, so what a caller gets back is a
    copy: changing it does not change what is cached, exactly as with any
    other backend. Turn that off to store the objects themselves, faster but
    shared.

    Every method completes without awaiting, so tasks on one event loop never
    see it half-updated. Two instances share nothing.
    """

    _values: dict[str, tuple[object, float | None]]
    _store_serialized: bool
    _max_lifetime: float
    _max_items: int
    _marshaller: MarshallerInterface

    def __init__(  # noqa: PLR0913 — every option past the lifetime is keyword-only.
        self,
        default_lifetime: float = 0.0,
        *,
        store_serialized: bool = True,
        max_lifetime: float = 0.0,
        max_items: int = 0,
        marshaller: MarshallerInterface | None = None,
        clock: ClockInterface | None = None,
    ) -> None:
        """Keep values in memory.

        Args:
            default_lifetime: Seconds a value lives when its item sets no
                expiry; ``0`` for no limit.
            store_serialized: Store a serialized copy rather than the object.
            max_lifetime: Seconds no value outlives, whatever its item says;
                ``0`` for no cap.
            max_items: How many values to keep, dropping the least recently
                used beyond; ``0`` for no limit.
            marshaller: What serializes values when ``store_serialized``.
                Pickle when omitted.
            clock: What lifetimes are counted from. ``None`` reads the clock
                in force.

        Raises:
            InvalidArgumentError: When ``max_lifetime`` or ``max_items`` is negative.
        """
        if max_lifetime < 0:
            raise InvalidArgumentError(f"max_lifetime must not be negative, got {max_lifetime}.")
        if max_items < 0:
            raise InvalidArgumentError(f"max_items must not be negative, got {max_items}.")

        super().__init__("", default_lifetime, clock=clock)
        self._values = {}
        self._store_serialized = store_serialized
        self._max_lifetime = max_lifetime
        self._max_items = max_items
        self._marshaller = marshaller if marshaller is not None else DefaultMarshaller()

    def values(self) -> dict[str, object]:
        """Return every live value by identifier, as stored; for tests."""
        now = self._clock.now().timestamp()
        return {
            id_: stored
            for id_, (stored, expiry) in self._values.items()
            if expiry is None or expiry > now
        }

    @override
    async def _do_fetch(self, ids: Sequence[str]) -> Mapping[str, object]:
        now = self._clock.now().timestamp()
        found: dict[str, object] = {}
        for id_ in ids:
            entry = self._values.get(id_)
            if entry is None:
                continue
            stored, expiry = entry
            if expiry is not None and expiry <= now:
                del self._values[id_]
                continue
            if self._max_items:
                # Most recently used last, so eviction takes from the front.
                self._values[id_] = self._values.pop(id_)
            if not self._store_serialized:
                found[id_] = stored
                continue
            try:
                # Stored serialized, so what is stored is the marshaller's bytes.
                found[id_] = self._marshaller.unmarshall(cast("bytes", stored))
            except MarshallingError as error:
                del self._values[id_]
                self._log('Failed to read key "{key}": {reason}', error, key=id_)

        return found

    @override
    async def _do_have(self, id_: str) -> bool:
        entry = self._values.get(id_)
        if entry is None:
            return False
        expiry = entry[1]
        return expiry is None or expiry > self._clock.now().timestamp()

    @override
    async def _do_clear(self, namespace: str) -> bool:
        if not namespace:
            self._values.clear()
        else:
            for id_ in [id_ for id_ in self._values if id_.startswith(namespace)]:
                del self._values[id_]
        return True

    @override
    async def _do_delete(self, ids: Sequence[str]) -> bool:
        for id_ in ids:
            _ = self._values.pop(id_, None)
        return True

    @override
    async def _do_save(self, values: Mapping[str, object], lifetime: float) -> bool | Sequence[str]:
        if self._max_lifetime and (not lifetime or lifetime > self._max_lifetime):
            lifetime = self._max_lifetime
        expiry = self._clock.now().timestamp() + lifetime if lifetime else None

        failed: list[str] = []
        stored: Mapping[str, object] = values
        if self._store_serialized:
            stored, failed = self._marshaller.marshall(values)

        for id_, value in stored.items():
            _ = self._values.pop(id_, None)
            self._values[id_] = (value, expiry)

        if self._max_items:
            while len(self._values) > self._max_items:
                del self._values[next(iter(self._values))]

        return failed or True

    @override
    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._default_lifetime!r})"
