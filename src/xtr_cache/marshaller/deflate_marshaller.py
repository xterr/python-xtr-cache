"""Compresses what another marshaller encodes."""

from __future__ import annotations

import zlib
from typing import TYPE_CHECKING, final

from typing_extensions import override

from .marshaller_interface import MarshallerInterface

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["DeflateMarshaller"]


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
        try:
            inflated = zlib.decompress(value)
        except zlib.error:
            # Written before compression was switched on: read it as it is.
            inflated = value

        return self._marshaller.unmarshall(inflated)

    @override
    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._marshaller!r})"
