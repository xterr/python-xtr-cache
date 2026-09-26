"""Builds an adapter from a DSN, a keyword, or a connection."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, final

from xtr_lock.store import is_redis_client, is_redis_dsn, redis_installed

from xtr_cache.exception import InvalidArgumentError

from .array_adapter import ArrayAdapter
from .filesystem_adapter import FilesystemAdapter
from .null_adapter import NullAdapter
from .redis_adapter import RedisAdapter

if TYPE_CHECKING:
    import os

    from xtr_clock import ClockInterface

    from xtr_cache.marshaller.marshaller_interface import MarshallerInterface

    from .adapter_interface import AdapterInterface

__all__ = ["AdapterFactory"]

_FILESYSTEM: Final = "filesystem"
_FILESYSTEM_PREFIX: Final = "filesystem://"
_KEYWORDS: Final = ("array", "null", _FILESYSTEM)


@final
class AdapterFactory:
    """Turns what a configuration names into an adapter.

    | Given | Adapter |
    |---|---|
    | ``"array"`` | :class:`ArrayAdapter` |
    | ``"null"`` | :class:`NullAdapter` |
    | ``"filesystem"`` | :class:`FilesystemAdapter` in ``directory``, or the temporary one |
    | ``"filesystem:///var/cache/app"`` | :class:`FilesystemAdapter` in that directory |
    | ``"redis://…"``, ``"rediss://…"``, ``"unix://…"`` | :class:`RedisAdapter`, its own client |
    | ``"valkey://…"``, ``"valkeys://…"`` | the same, read as ``redis`` / ``rediss`` |
    | an asyncio Redis client | :class:`RedisAdapter` on that client |
    """

    __slots__ = ()

    @staticmethod
    def create_adapter(  # noqa: PLR0913 — every option past the connection is keyword-only.
        connection: object,
        namespace: str = "",
        default_lifetime: float = 0.0,
        *,
        marshaller: MarshallerInterface | None = None,
        directory: str | os.PathLike[str] | None = None,
        clock: ClockInterface | None = None,
    ) -> AdapterInterface:
        """Build the adapter ``connection`` names.

        Args:
            connection: A DSN, a keyword, or an asyncio Redis client.
            namespace: The pool's namespace; an in-memory pool has no use for one.
            default_lifetime: Seconds a value lives when its item sets no expiry.
            marshaller: What turns values into bytes, for a backend storing bytes.
            directory: Where ``"filesystem"`` keeps its files.
            clock: What lifetimes are counted from.

        Raises:
            InvalidArgumentError: When no adapter serves ``connection``. The
                message names its scheme or type only, never credentials.
        """
        if is_redis_client(connection):
            return RedisAdapter(
                connection,
                namespace,
                default_lifetime,
                marshaller=marshaller,
                clock=clock,
            )

        if not isinstance(connection, str):
            raise InvalidArgumentError(
                f'Unsupported cache connection: "{type(connection).__qualname__}".',
            )

        AdapterFactory.validate(connection)

        if connection == "array":
            return ArrayAdapter(default_lifetime, marshaller=marshaller, clock=clock)
        if connection == "null":
            return NullAdapter()
        if connection == _FILESYSTEM or connection.startswith(_FILESYSTEM_PREFIX):
            path = (
                connection.removeprefix(_FILESYSTEM_PREFIX) if connection != _FILESYSTEM else None
            )
            return FilesystemAdapter(
                namespace,
                default_lifetime,
                path or directory,
                marshaller=marshaller,
                clock=clock,
            )

        # The only thing validate() lets through that is not handled above.
        return RedisAdapter.from_url(
            connection,
            namespace,
            default_lifetime,
            marshaller=marshaller,
            clock=clock,
        )

    @staticmethod
    def validate(connection: str) -> None:
        """Refuse a DSN no adapter serves, without building one or connecting to anything.

        Raises:
            InvalidArgumentError: When no adapter serves ``connection``, or it
                needs an extra that is not installed. The message names its
                scheme only, never credentials.
        """
        if connection in _KEYWORDS or connection.startswith(_FILESYSTEM_PREFIX):
            return

        if is_redis_dsn(connection):
            if not redis_installed():
                raise InvalidArgumentError(RedisAdapter.MISSING_CLIENT)
            return

        scheme, separator, _ = connection.partition(":")
        described = f"{scheme}:" if separator else connection

        raise InvalidArgumentError(f'Unsupported cache connection: "{described}".')
