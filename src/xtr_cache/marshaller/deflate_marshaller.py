"""Compresses what another marshaller encodes."""

from __future__ import annotations

import zlib
from typing import TYPE_CHECKING, Final, final

from typing_extensions import override

from xtr_cache.exception import MarshallingError

from .marshaller_interface import MarshallerInterface

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["DeflateMarshaller"]

_HEADER_LENGTH: Final = 2
_DEFLATE: Final = 8
"""The compression method a zlib header names in its low four bits."""


@final
class DeflateMarshaller(MarshallerInterface):
    """Compresses the bytes another marshaller produces, trading CPU for backend memory.

    Reading bytes that are not compressed hands them to the inner marshaller
    as they are, so a pool can start compressing without being cleared first.
    """

    __slots__ = ("_marshaller",)

    _marshaller: MarshallerInterface

    def __init__(self, marshaller: MarshallerInterface) -> None:
        """Compress what ``marshaller`` encodes."""
        self._marshaller = marshaller

    @override
    def marshall(self, values: Mapping[str, object], /) -> tuple[dict[str, bytes], list[str]]:
        encoded, failed = self._marshaller.marshall(values)
        return {key: zlib.compress(value) for key, value in encoded.items()}, failed

    @override
    def unmarshall(self, value: bytes, /) -> object:
        """Inflate ``value`` and decode it; bytes never compressed are decoded as they are.

        Raises:
            MarshallingError: If ``value`` is compressed but corrupt.
        """
        if not _compressed(value):
            # Written before compression was switched on: read it as it is.
            return self._marshaller.unmarshall(value)
        try:
            inflated = zlib.decompress(value)
        except zlib.error as error:
            raise MarshallingError(
                f"the stored value is compressed but corrupt: {error}"
            ) from error

        return self._marshaller.unmarshall(inflated)

    @override
    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._marshaller!r})"


def _compressed(value: bytes) -> bool:
    """Tell whether ``value`` starts with a zlib header: deflate, and a check that adds up."""
    return (
        len(value) >= _HEADER_LENGTH
        and value[0] & 0x0F == _DEFLATE
        and ((value[0] << 8) | value[1]) % 31 == 0
    )
