"""A pool on a Redis server, shared by every process that reaches it."""

from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING, ClassVar, Final, Protocol, cast, final

from typing_extensions import override
from xtr_lock import InvalidArgumentError as LockArgumentError
from xtr_lock.store import create_redis_client

from xtr_cache.exception import InvalidArgumentError
from xtr_cache.marshaller.default_marshaller import DefaultMarshaller

from .abstract_adapter import AbstractAdapter

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Mapping, Sequence

    from redis.asyncio import Redis
    from xtr_clock import ClockInterface

    from xtr_cache.marshaller.marshaller_interface import MarshallerInterface

__all__ = ["RedisAdapter"]

_GLOB_SPECIAL: Final = re.compile(r"([*?\[\]\\])")

_BATCH: Final = 1000
"""How many keys one scan step, or one unlink, handles."""


class _Pipeline(Protocol):
    """The two pipeline calls this adapter makes."""

    def set(self, name: str, value: bytes, px: int | None = None) -> object: ...

    def execute(self, raise_on_error: bool = True) -> Awaitable[list[object]]: ...


class _Client(Protocol):
    """The calls this adapter makes, typed as the asyncio client answers them.

    The client's own annotations cover its blocking twin too, so every reply
    is typed as possibly not awaitable.
    """

    def mget(self, keys: Sequence[str]) -> Awaitable[list[bytes | None]]: ...

    def exists(self, *names: str) -> Awaitable[int]: ...

    def unlink(self, *names: str) -> Awaitable[int]: ...

    def scan_iter(
        self, match: str | None = None, count: int | None = None
    ) -> AsyncIterator[bytes]: ...

    def pipeline(self, transaction: bool = True) -> _Pipeline: ...

    def get_connection_kwargs(self) -> Mapping[str, object]: ...


@final
class RedisAdapter(AbstractAdapter):
    """Keeps values on a Redis or Valkey server, which expires them on its own.

    Each value is a string key: the pool's namespace, then the key. Saves are
    pipelined, reads fetch many keys in one round trip, and clearing scans the
    namespace's keys and unlinks them in batches — without a namespace, that
    is every key in the database.

    One server, standalone. Not a cluster, not Sentinel.
    """

    MISSING_CLIENT: ClassVar[str] = (
        'A Redis cache pool needs the redis client; install "xtr-cache[redis]".'
    )
    """What a Redis DSN is refused with when the client library is not installed."""

    _redis: Redis
    _client: _Client
    _marshaller: MarshallerInterface
    _owns_connection: bool

    def __init__(
        self,
        redis: Redis,
        namespace: str = "",
        default_lifetime: float = 0.0,
        *,
        marshaller: MarshallerInterface | None = None,
        clock: ClockInterface | None = None,
    ) -> None:
        """Keep values on the server ``redis`` talks to; the client stays the caller's to close.

        Args:
            redis: An asyncio client.
            namespace: Put in front of every key. Set one when the database
                holds anything else.
            default_lifetime: Seconds a value lives when its item sets no
                expiry; ``0`` for no limit.
            marshaller: What turns values into bytes. Pickle when omitted.
            clock: What item lifetimes are counted from. ``None`` reads the
                clock in force.

        Raises:
            InvalidArgumentError: When the client decodes replies into text:
                stored values are bytes, and would never read back.
        """
        # The client is typed for its blocking twin too; see _Client.
        client = cast("_Client", cast("object", redis))
        if client.get_connection_kwargs().get("decode_responses"):
            raise InvalidArgumentError(
                "A Redis cache pool needs a client returning bytes; "
                "this one was created with decode_responses=True.",
            )

        super().__init__(namespace, default_lifetime, clock=clock)
        self._redis = redis
        self._client = client
        self._marshaller = marshaller if marshaller is not None else DefaultMarshaller()
        self._owns_connection = False

    @classmethod
    def from_url(
        cls,
        dsn: str,
        namespace: str = "",
        default_lifetime: float = 0.0,
        *,
        marshaller: MarshallerInterface | None = None,
        clock: ClockInterface | None = None,
    ) -> RedisAdapter:
        """Connect to the server ``dsn`` names, on first use, and own the connection.

        Close the adapter with :meth:`aclose` when done.

        Raises:
            InvalidArgumentError: When the scheme is not a Redis one, or the
                ``redis`` extra is not installed.
        """
        adapter = cls(
            cls.create_connection(dsn),
            namespace,
            default_lifetime,
            marshaller=marshaller,
            clock=clock,
        )
        adapter._owns_connection = True
        return adapter

    @staticmethod
    def create_connection(dsn: str) -> Redis:
        """Return an asyncio client for ``dsn`` that connects on first use.

        ``valkey://`` and ``valkeys://`` read as ``redis://`` and ``rediss://``.

        Raises:
            InvalidArgumentError: When the scheme is not a Redis one, or the
                ``redis`` extra is not installed. The message names the
                scheme only, never credentials.
        """
        try:
            return create_redis_client(dsn, missing=RedisAdapter.MISSING_CLIENT)
        except LockArgumentError as error:
            raise InvalidArgumentError(error.reason) from error

    @property
    def owns_connection(self) -> bool:
        """Whether :meth:`aclose` closes the client, because :meth:`from_url` opened it."""
        return self._owns_connection

    async def aclose(self) -> None:
        """Close the connection, when :meth:`from_url` opened it; otherwise do nothing."""
        if self._owns_connection:
            await self._redis.aclose()

    @override
    async def _do_fetch(self, ids: Sequence[str]) -> Mapping[str, object]:
        if not ids:
            return {}

        replies = await self._client.mget(list(ids))
        raw = {id_: reply for id_, reply in zip(ids, replies, strict=True) if reply is not None}
        return self._unmarshall_found(self._marshaller, raw)

    @override
    async def _do_have(self, id_: str) -> bool:
        return bool(await self._client.exists(id_))

    @override
    async def _do_clear(self, namespace: str) -> bool:
        match = _GLOB_SPECIAL.sub(r"\\\1", namespace) + "*"
        batch: list[str] = []
        async for key in self._client.scan_iter(match=match, count=_BATCH):
            batch.append(key.decode())
            if len(batch) >= _BATCH:
                _ = await self._client.unlink(*batch)
                batch = []
        if batch:
            _ = await self._client.unlink(*batch)

        return True

    @override
    async def _do_delete(self, ids: Sequence[str]) -> bool:
        if ids:
            _ = await self._client.unlink(*ids)
        return True

    @override
    async def _do_save(self, values: Mapping[str, object], lifetime: float) -> bool | Sequence[str]:
        encoded, failed = self._marshaller.marshall(values)
        if not encoded:
            return failed or True

        milliseconds = math.ceil(lifetime * 1000) if lifetime else None
        pipeline = self._client.pipeline(transaction=False)
        for id_, data in encoded.items():
            _ = pipeline.set(id_, data, px=milliseconds)
        replies = await pipeline.execute(raise_on_error=False)

        for id_, reply in zip(encoded, replies, strict=True):
            if isinstance(reply, Exception):
                failed.append(id_)
                self._log('Failed to save key "{key}": {reason}', reply, key=id_)

        return failed or True

    @override
    def __repr__(self) -> str:
        name = type(self).__name__
        return f"{name}({self._redis!r}, {self._namespace!r}, {self._default_lifetime!r})"
