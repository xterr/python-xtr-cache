"""An adapter over a dictionary whose backend can be told to fail, one operation at a time."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, final

from typing_extensions import override

from xtr_cache import AbstractAdapter

if TYPE_CHECKING:
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
    """

    max_id_length: ClassVar[int | None] = None

    def __init__(self, namespace: str = "", default_lifetime: float = 0.0) -> None:
        super().__init__(namespace, default_lifetime)
        self.stored: dict[str, tuple[object, float | None]] = {}
        self.fail: set[str] = set()
        self.refuse_batches = False
        self.refuse_all = False
        self.reject: set[str] = set()
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    @override
    async def _do_fetch(self, ids: Sequence[str]) -> Mapping[str, object]:
        self._record("fetch", ids)
        now = self._clock.now().timestamp()
        return {
            id_: value
            for id_ in ids
            if (entry := self.stored.get(id_)) is not None
            for value, expiry in [entry]
            if expiry is None or expiry > now
        }

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
        if self.refuse_all or (self.refuse_batches and len(ids) > 1):
            return False
        for id_ in ids:
            _ = self.stored.pop(id_, None)
        return True

    @override
    async def _do_save(self, values: Mapping[str, object], lifetime: float) -> bool | Sequence[str]:
        self._record("save", list(values))
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
            raise BackendDownError(operation)
