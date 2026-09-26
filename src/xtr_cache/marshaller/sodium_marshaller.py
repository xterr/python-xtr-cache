"""Encrypts what another marshaller encodes, and refuses what it did not encrypt."""

from __future__ import annotations

import base64
import binascii
import importlib.util
from typing import TYPE_CHECKING, Final, final

from typing_extensions import override

from xtr_cache.exception import InvalidArgumentError, MarshallingError

from .default_marshaller import DefaultMarshaller
from .marshaller_interface import MarshallerInterface

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from nacl.secret import SecretBox

__all__ = ["SodiumMarshaller"]

_KEY_SIZE: Final = 32


@final
class SodiumMarshaller(MarshallerInterface):
    """Encrypts stored values with libsodium's authenticated secret-key encryption.

    What it writes can be neither read nor forged without a key: a Redis
    server shared with other applications sees only ciphertext, and bytes
    anyone else wrote fail authentication before they reach the inner
    marshaller — so pickle never unpickles them. Such a value reads as a
    miss, and the pool computes it again.

    Keys rotate: the first encrypts, and every one of them decrypts. To
    rotate, put the new key first and keep the old one until what it
    encrypted has expired.

    Needs the ``sodium`` extra: ``xtr-cache[sodium]``.
    """

    __slots__ = ("_boxes", "_marshaller")

    _boxes: tuple[SecretBox, ...]
    _marshaller: MarshallerInterface

    def __init__(
        self,
        decryption_keys: Sequence[bytes | str],
        marshaller: MarshallerInterface | None = None,
    ) -> None:
        """Encrypt with the first of ``decryption_keys``, decrypt with any of them.

        Args:
            decryption_keys: 32-byte keys, raw or base64-encoded, the one to
                encrypt with first. :meth:`generate_key` makes one.
            marshaller: What encodes the values before they are encrypted.
                Pickle when omitted.

        Raises:
            InvalidArgumentError: When no key is given, a key is not 32 bytes,
                or the ``sodium`` extra is not installed.
        """
        if not decryption_keys:
            raise InvalidArgumentError("A sodium marshaller needs at least one decryption key.")

        try:
            from nacl.secret import SecretBox  # noqa: PLC0415 — the sodium extra is optional.
        except ImportError as error:
            raise InvalidArgumentError(
                'A sodium marshaller needs PyNaCl; install "xtr-cache[sodium]".',
            ) from error

        self._boxes = tuple(SecretBox(_key_bytes(key)) for key in decryption_keys)
        self._marshaller = marshaller if marshaller is not None else DefaultMarshaller()

    @staticmethod
    def is_supported() -> bool:
        """Tell whether PyNaCl is installed."""
        return importlib.util.find_spec("nacl") is not None

    @staticmethod
    def generate_key() -> str:
        """Return a new random key, base64-encoded, for configuration or an environment variable.

        Raises:
            InvalidArgumentError: When the ``sodium`` extra is not installed.
        """
        try:
            from nacl.utils import random  # noqa: PLC0415 — the sodium extra is optional.
        except ImportError as error:
            raise InvalidArgumentError(
                'Generating a sodium key needs PyNaCl; install "xtr-cache[sodium]".',
            ) from error

        return base64.b64encode(random(_KEY_SIZE)).decode("ascii")

    @override
    def marshall(self, values: Mapping[str, object], /) -> tuple[dict[str, bytes], list[str]]:
        encoded, failed = self._marshaller.marshall(values)
        box = self._boxes[0]

        return {key: bytes(box.encrypt(value)) for key, value in encoded.items()}, failed

    @override
    def unmarshall(self, value: bytes, /) -> object:
        from nacl.exceptions import CryptoError  # noqa: PLC0415 — installed, or __init__ refused.

        for box in self._boxes:
            try:
                decrypted = box.decrypt(value)
            except CryptoError:
                continue
            return self._marshaller.unmarshall(decrypted)

        raise MarshallingError("the stored value cannot be decrypted with any of the keys")

    @override
    def __repr__(self) -> str:
        # Never the keys: a repr ends up in logs.
        return f"{type(self).__name__}(<{len(self._boxes)} keys>, {self._marshaller!r})"


def _key_bytes(key: bytes | str) -> bytes:
    """Return ``key`` as raw bytes, decoding it from base64 when it is a string.

    Raises:
        InvalidArgumentError: When the key is not valid base64, or not 32 bytes.
    """
    if isinstance(key, str):
        try:
            key = base64.b64decode(key, validate=True)
        except (binascii.Error, ValueError) as error:
            raise InvalidArgumentError("A sodium key given as text must be base64.") from error

    if len(key) != _KEY_SIZE:
        raise InvalidArgumentError(
            f"A sodium key must be {_KEY_SIZE} bytes long, got {len(key)}.",
        )

    return key
