"""Turns cached values into bytes a backend stores, and back."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["MarshallerInterface"]


@runtime_checkable
class MarshallerInterface(Protocol):
    """Encodes values for a backend that stores bytes, and decodes what it returns.

    Encoding is batched and never raises: a value that cannot be encoded is
    reported by key, and the pool logs it and saves the rest. Decoding one
    value raises when the bytes cannot be read, and the pool treats that
    value as a miss. Stored bytes outlive a deployment, so an implementation
    must keep reading what an earlier version of itself wrote.
    """

    def marshall(self, values: Mapping[str, object], /) -> tuple[dict[str, bytes], list[str]]:
        """Encode ``values``.

        Returns:
            The encoded values by key, and the keys of the values that could
            not be encoded.
        """
        ...

    def unmarshall(self, value: bytes, /) -> object:
        """Decode one stored value.

        Raises:
            MarshallingError: When ``value`` cannot be decoded.
        """
        ...
