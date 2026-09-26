"""Values as pickles: any Python object that pickles round-trips."""

from __future__ import annotations

import pickle
from typing import TYPE_CHECKING, cast, final

from typing_extensions import override

from xtr_cache.exception.marshalling_error import MarshallingError

from .marshaller_interface import MarshallerInterface

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["DefaultMarshaller"]


@final
class DefaultMarshaller(MarshallerInterface):
    """Encodes values with :mod:`pickle`, the one format every Python object can take.

    A cache holds values of any type and reads them back without being told
    which, so the format has to carry the type itself: a dataclass comes back
    a dataclass, not a dictionary.

    Unpickling runs code named by the bytes. That is safe as long as only
    this application can write to the backend. When anything else can — a
    Redis server shared with other applications — wrap this marshaller in a
    :class:`~xtr_cache.marshaller.sodium_marshaller.SodiumMarshaller`, which
    refuses bytes not encrypted with its key before they reach pickle.
    """

    __slots__ = ()

    @override
    def marshall(self, values: Mapping[str, object], /) -> tuple[dict[str, bytes], list[str]]:
        encoded: dict[str, bytes] = {}
        failed: list[str] = []
        for key, value in values.items():
            try:
                encoded[key] = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
            except (pickle.PicklingError, TypeError, AttributeError, RecursionError):
                failed.append(key)

        return encoded, failed

    @override
    def unmarshall(self, value: bytes, /) -> object:
        try:
            # Only this application writes what is read here; see the class docstring.
            # pickle.loads is typed as returning Any; what it returns is any object.
            return cast("object", pickle.loads(value))  # noqa: S301
        # Unpickling can raise whatever the stored object's reconstruction raises.
        except Exception as error:
            raise MarshallingError(f"the stored value cannot be unpickled: {error}") from error

    @override
    def __repr__(self) -> str:
        return f"{type(self).__name__}()"
