"""An adapter over a dictionary whose backend can be told to fail, one operation at a time."""

from __future__ import annotations

from typing import TYPE_CHECKING, final, override

from xtr_cache import AbstractAdapter

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Mapping, Sequence

__all__ = ["BackendDownError", "ScriptedAdapter"]


class BackendDownError(RuntimeError):
    """What a scripted backend raises."""


@final
class ScriptedAdapter(AbstractAdapter):
    """Stores values in a dictionary, honouring lifetimes, unless told to fail.

    ``fail`` names the operations that raise (``"fetch"``, ``"have"``,
    ``"clear"``, ``"delete"``, ``"save"``). ``refuse_batches`` makes a delete
    or save of several values return ``False`` without saying why, while one
    value at a time succeeds; ``refuse_all`` refuses one value too.
    ``reject`` lists identifiers a save reports as
    failed. Every call is recorded in ``calls``.
    ``pause_before`` and ``pause_after`` hold an operation on an event, once:
    before it touches the dictionary, or after it read what it returns.
    """

    def __init__(self, namespace: str = "", default_lifetime: float = 0.0) -> None:
        super().__init__(namespace, default_lifetime)
        self.stored: dict[str, tuple[object, float | None]] = {}
        self.fail: set[str] = set()
        # What a failing operation raises instead of BackendDownError, when set.
        self.error: Exception | None = None
        self.refuse_batches = False
        self.refuse_all = False
        self.reject: set[str] = set()
        self.calls: list[tuple[str, tuple[str, ...]]] = []
        self.pause_before: dict[str, asyncio.Event] = {}
        self.pause_after: dict[str, asyncio.Event] = {}

    @override
    async def _do_fetch(self, ids: Sequence[str]) -> Mapping[str, object]:
        self._record("fetch", ids)
        await self._pause(self.pause_before, "fetch")
        now = self._clock.now().timestamp()
        found = {
            id_: value
            for id_ in ids
            if (entry := self.stored.get(id_)) is not None
            for value, expiry in [entry]
            if expiry is None or expiry > now
        }
        await self._pause(self.pause_after, "fetch")
        return found

    @override
    async def _do_have(self, id_: str) -> bool:
        self._record("have", [id_])
        return id_ in await self._do_fetch([id_])

    @override
    async def _do_clear(self, namespace: str) -> bool:
        self._record("clear", [namespace])
        for id_ in [id_ for id_ in self.stored if id_.startswith(namespace)]:
            del self.stored[id_]
        return True

    @override
    async def _do_delete(self, ids: Sequence[str]) -> bool:
        self._record("delete", ids)
        await self._pause(self.pause_before, "delete")
        if self.refuse_all or (self.refuse_batches and len(ids) > 1):
            return False
        for id_ in ids:
            _ = self.stored.pop(id_, None)
        return True

    @override
    async def _do_save(self, values: Mapping[str, object], lifetime: float) -> bool | Sequence[str]:
        self._record("save", list(values))
        await self._pause(self.pause_before, "save")
        if self.refuse_all or (self.refuse_batches and len(values) > 1):
            return False
        expiry = self._clock.now().timestamp() + lifetime if lifetime else None
        failed = [id_ for id_ in values if id_ in self.reject]
        for id_, value in values.items():
            if id_ not in self.reject:
                self.stored[id_] = (value, expiry)
        return failed or True

    def _record(self, operation: str, ids: Sequence[str]) -> None:
        self.calls.append((operation, tuple(ids)))
        if operation in self.fail:
            if self.error is not None:
                raise self.error
            raise BackendDownError(operation)

    @staticmethod
    async def _pause(pauses: dict[str, asyncio.Event], operation: str) -> None:
        event = pauses.pop(operation, None)
        if event is not None:
            _ = await event.wait()
