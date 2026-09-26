"""The shared machinery of a pool over a key-value backend."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import math
import re
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, ClassVar, Final, Self

from typing_extensions import override
from xtr_cache_contracts import InvalidArgumentError, NamespacedPoolInterface

from xtr_cache.cache_item import CacheItem
from xtr_cache.exception.marshalling_error import MarshallingError

from .adapter_interface import AdapterInterface
from .contracts_mixin import ContractsMixin
from .deferred_items_mixin import DeferredItemsMixin

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from xtr_clock import ClockInterface

    from xtr_cache.marshaller.marshaller_interface import MarshallerInterface

__all__ = ["AbstractAdapter"]

_PREFIX_PATTERN: Final = re.compile(r"[-+.:_A-Za-z0-9]*")

_MISSING: Final = object()


class AbstractAdapter(
    DeferredItemsMixin, ContractsMixin, AdapterInterface, NamespacedPoolInterface, ABC
):
    """A pool whose backend stores values by identifier, with a lifetime each.

    A subclass implements five operations on identifiers — fetch, has, clear,
    delete, save — and gets every pool method on top: keys validated and
    namespaced, deferred saves committed in batches by lifetime, sub-namespaces,
    fetch-or-compute, and failures logged instead of raised. A backend that
    cannot be reached makes reads miss and writes return ``False``; the code
    caching keeps running.

    An identifier is the pool's namespace followed by the key. A backend with
    a limit on identifier length sets :attr:`max_id_length`, and keys that
    would exceed it are hashed.
    """

    NS_SEPARATOR: ClassVar[str] = ":"
    """What separates a namespace from what follows it in an identifier."""

    max_id_length: ClassVar[int | None] = None
    """The longest identifier the backend takes, or ``None`` for no limit."""

    _namespace: str
    _default_lifetime: float
    _clock: ClockInterface
    _deferred: dict[str, CacheItem]

    def __init__(
        self,
        namespace: str = "",
        default_lifetime: float = 0.0,
        *,
        clock: ClockInterface | None = None,
    ) -> None:
        """Keep values under ``namespace``, living ``default_lifetime`` unless an item says not.

        Args:
            namespace: Put in front of every key; ``:`` separates
                sub-namespaces. Empty for none.
            default_lifetime: Seconds a value lives when its item sets no
                expiry; ``0`` keeps it until it is deleted.
            clock: What lifetimes are counted from. ``None`` reads the clock
                in force.

        Raises:
            InvalidArgumentError: When ``namespace`` is not a valid key once
                its separators are removed, has an empty sub-namespace, or
                leaves no room for keys within :attr:`max_id_length`.
        """
        if namespace:
            if self.NS_SEPARATOR * 2 in namespace:
                raise InvalidArgumentError(
                    f'Cache namespace "{namespace}" contains an empty sub-namespace.',
                )
            _ = CacheItem.validate_key(namespace.replace(self.NS_SEPARATOR, ""))
            if self.max_id_length is not None and len(namespace) > self.max_id_length - 24:
                raise InvalidArgumentError(
                    f"A cache namespace must be {self.max_id_length - 24} characters at most, "
                    f"got {len(namespace)}.",
                )
            namespace += self.NS_SEPARATOR

        self._namespace = namespace
        self._default_lifetime = default_lifetime
        self._deferred = {}
        if clock is not None:
            self._clock = clock

    @property
    def namespace(self) -> str:
        """What every identifier starts with, separator included; empty for none."""
        return self._namespace

    @property
    def default_lifetime(self) -> float:
        """Seconds a value lives when its item sets no expiry; ``0`` for no limit."""
        return self._default_lifetime

    @abstractmethod
    async def _do_fetch(self, ids: Sequence[str]) -> Mapping[str, object]:
        """Return the stored value of every identifier the backend holds, leaving out the rest."""

    @abstractmethod
    async def _do_have(self, id_: str) -> bool:
        """Tell whether the backend holds a live value under ``id_``."""

    @abstractmethod
    async def _do_clear(self, namespace: str) -> bool:
        """Remove every value whose identifier starts with ``namespace``; all of them when empty."""

    @abstractmethod
    async def _do_delete(self, ids: Sequence[str]) -> bool:
        """Remove the values under ``ids``; ``False`` when that failed."""

    @abstractmethod
    async def _do_save(self, values: Mapping[str, object], lifetime: float) -> bool | Sequence[str]:
        """Store ``values`` by identifier for ``lifetime`` seconds, ``0`` meaning no limit.

        Returns:
            ``True`` when every value was stored, ``False`` when none could
            be and why is unknown, or the identifiers that failed.
        """

    @override
    async def get_item(self, key: str, /) -> CacheItem:
        id_ = self._get_id(key)
        await self._commit_if_queued([key])

        try:
            found = await self._do_fetch([id_])
        except Exception as error:  # noqa: BLE001 — a cache failure must never fail the caller.
            self._log('Failed to fetch key "{key}": {reason}', error, key=key)
            return self._create_item(key)

        stored = found.get(id_, _MISSING)
        if stored is _MISSING:
            return self._create_item(key)

        return self._create_item(key, stored)

    @override
    async def get_items(self, keys: Iterable[str], /) -> Mapping[str, CacheItem]:
        wanted = list(dict.fromkeys(keys))
        ids = {key: self._get_id(key) for key in wanted}
        await self._commit_if_queued(wanted)

        found: Mapping[str, object] = {}
        try:
            found = await self._do_fetch(list(ids.values()))
        except Exception as error:  # noqa: BLE001 — a cache failure must never fail the caller.
            self._log("Failed to fetch items: {reason}", error, keys=wanted)

        items: dict[str, CacheItem] = {}
        for key, id_ in ids.items():
            stored = found.get(id_, _MISSING)
            items[key] = (
                self._create_item(key) if stored is _MISSING else self._create_item(key, stored)
            )

        return items

    @override
    async def has_item(self, key: str, /) -> bool:
        id_ = self._get_id(key)
        await self._commit_if_queued([key])

        try:
            return await self._do_have(id_)
        except Exception as error:  # noqa: BLE001 — a cache failure must never fail the caller.
            self._log('Failed to check if key "{key}" is cached: {reason}', error, key=key)
            return False

    @override
    async def clear(self, prefix: str = "") -> bool:
        self._drop_deferred(prefix)
        if not _PREFIX_PATTERN.fullmatch(prefix):
            self._log("Failed to clear the cache: the prefix contains invalid characters.")
            return False

        try:
            return await self._do_clear(self._namespace + prefix)
        except Exception as error:  # noqa: BLE001 — a cache failure must never fail the caller.
            self._log("Failed to clear the cache: {reason}", error)
            return False

    @override
    async def delete_item(self, key: str, /) -> bool:
        return await self.delete_items([key])

    @override
    async def delete_items(self, keys: Iterable[str], /) -> bool:
        ids = {key: self._get_id(key) for key in keys}
        self._forget_deferred(ids)

        if not ids:
            return True

        # A batch failing is retried one key at a time below, where each failure is logged.
        with contextlib.suppress(Exception):
            if await self._do_delete(list(ids.values())):
                return True

        ok = True
        for key, id_ in ids.items():
            try:
                if await self._do_delete([id_]):
                    continue
                self._log('Failed to delete key "{key}".', key=key)
            except Exception as error:  # noqa: BLE001 — a cache failure must never fail the caller.
                self._log('Failed to delete key "{key}": {reason}', error, key=key)
            ok = False

        return ok

    @override
    async def commit(self) -> bool:
        deferred, self._deferred = self._deferred, {}
        if not deferred:
            return True

        now = self._clock.now().timestamp()
        default_expiry = now + self._default_lifetime if self._default_lifetime > 0 else None
        by_lifetime: dict[float, dict[str, object]] = {}
        keys_by_id: dict[str, str] = {}
        expired: list[str] = []
        for key, item in deferred.items():
            id_ = self._get_id(key)
            keys_by_id[id_] = key
            if item.expiry is None:
                lifetime = max(self._default_lifetime, 0.0)
            else:
                lifetime = math.ceil((item.expiry - now) * 1000) / 1000
                if lifetime <= 0:
                    expired.append(id_)
                    continue
            by_lifetime.setdefault(lifetime, {})[id_] = item.pack(default_expiry)

        ok = True
        if expired:
            try:
                _ = await self._do_delete(expired)
            except Exception as error:  # noqa: BLE001 — a cache failure must never fail the caller.
                ok = False
                self._log("Failed to delete expired items: {reason}", error)

        for lifetime, values in by_lifetime.items():
            ok = await self._save_batch(values, lifetime, keys_by_id) and ok

        return ok

    @override
    def with_sub_namespace(self, namespace: str, /) -> Self:
        clone = self._unqueued_copy()
        clone._namespace = (  # noqa: SLF001 — a copy of this very class.
            self._namespace + CacheItem.validate_key(namespace) + self.NS_SEPARATOR
        )
        return clone

    @override
    def _scope(self) -> str:
        return self._namespace

    async def _save_batch(
        self,
        values: Mapping[str, object],
        lifetime: float,
        keys_by_id: Mapping[str, str],
    ) -> bool:
        """Save one batch, retrying value by value when the backend did not say what failed."""
        error: Exception | None = None
        try:
            result = await self._do_save(values, lifetime)
        except Exception as raised:  # noqa: BLE001 — logged below, per value.
            result, error = False, raised

        if result is True:
            return True
        if result is not False:
            for id_ in result:
                self._log_save_failure(keys_by_id[id_], values[id_])
            return len(result) == 0
        if len(values) == 1:
            for id_, value in values.items():
                self._log_save_failure(keys_by_id[id_], value, error)
            return False

        ok = True
        for id_, value in values.items():
            ok = await self._save_batch({id_: value}, lifetime, keys_by_id) and ok

        return ok

    def _create_item(self, key: str, stored: object = _MISSING) -> CacheItem:
        if stored is _MISSING:
            return CacheItem(key, clock=self._clock)

        return CacheItem.from_stored(key, stored, clock=self._clock)

    def _get_id(self, key: str) -> str:
        """Return the backend identifier of ``key``, hashing it when it would be too long.

        Raises:
            InvalidArgumentError: When ``key`` is not a valid key.
        """
        id_ = self._namespace + CacheItem.validate_key(key)
        if self.max_id_length is None or len(id_) <= self.max_id_length:
            return id_

        digest = base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest()[:16]).decode()
        return self._namespace + digest.rstrip("=") + self.NS_SEPARATOR

    def _unmarshall_found(
        self,
        marshaller: MarshallerInterface,
        raw: Mapping[str, bytes],
    ) -> dict[str, object]:
        """Decode what a byte backend returned, leaving out — and logging — what does not decode."""
        values: dict[str, object] = {}
        for id_, data in raw.items():
            try:
                values[id_] = marshaller.unmarshall(data)
            except MarshallingError as error:
                self._log('Failed to read key "{key}": {reason}', error, key=id_)

        return values

    def _log_save_failure(self, key: str, value: object, error: Exception | None = None) -> None:
        kind = type(value).__qualname__
        if error is None:
            self._log(f'Failed to save key "{{key}}" of type {kind}.', key=key)
        else:
            self._log(f'Failed to save key "{{key}}" of type {kind}: {{reason}}', error, key=key)

    def _log(self, message: str, error: Exception | None = None, **context: object) -> None:
        context["cache_adapter"] = type(self).__name__
        if error is not None:
            context["exception"] = error
            context["reason"] = str(error)
        self.logger.warning(message, context)
