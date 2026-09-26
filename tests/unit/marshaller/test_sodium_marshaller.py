from __future__ import annotations

import base64
import builtins
import pickle
import threading
from typing import TYPE_CHECKING, cast

import pytest

from xtr_cache import (
    DefaultMarshaller,
    DeflateMarshaller,
    InvalidArgumentError,
    MarshallingError,
    SodiumMarshaller,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

KEY = SodiumMarshaller.generate_key()
OLD_KEY = SodiumMarshaller.generate_key()


def test_values_are_encrypted_and_read_back() -> None:
    marshaller = SodiumMarshaller([KEY])

    encoded, failed = marshaller.marshall({"secret": "plain text"})

    assert failed == []
    assert b"plain text" not in encoded["secret"]
    assert marshaller.unmarshall(encoded["secret"]) == "plain text"


def test_the_first_key_encrypts_and_every_key_decrypts() -> None:
    old = SodiumMarshaller([OLD_KEY])
    rotated = SodiumMarshaller([KEY, OLD_KEY])
    written_before, _ = old.marshall({"a": 1})
    written_after, _ = rotated.marshall({"a": 2})

    assert rotated.unmarshall(written_before["a"]) == 1
    assert rotated.unmarshall(written_after["a"]) == 2
    with pytest.raises(MarshallingError):
        _ = old.unmarshall(written_after["a"])


def test_bytes_not_encrypted_with_a_key_never_reach_the_inner_marshaller() -> None:
    forged = pickle.dumps("anything an attacker wrote")

    with pytest.raises(MarshallingError, match="cannot be decrypted with any of the keys"):
        _ = SodiumMarshaller([KEY]).unmarshall(forged)


def test_what_the_inner_marshaller_cannot_encode_is_reported() -> None:
    encoded, failed = SodiumMarshaller([KEY]).marshall({"lock": threading.Lock(), "ok": 1})

    assert failed == ["lock"]
    assert set(encoded) == {"ok"}


def test_it_wraps_any_marshaller() -> None:
    marshaller = SodiumMarshaller([KEY], DeflateMarshaller(DefaultMarshaller()))

    encoded, _ = marshaller.marshall({"a": "x" * 1000})

    assert marshaller.unmarshall(encoded["a"]) == "x" * 1000


def test_keys_are_raw_bytes_or_base64_text() -> None:
    raw = base64.b64decode(KEY)
    from_bytes, _ = SodiumMarshaller([raw]).marshall({"a": 1})

    assert SodiumMarshaller([KEY]).unmarshall(from_bytes["a"]) == 1


@pytest.mark.parametrize(
    ("keys", "reason"),
    [
        ([], "at least one decryption key"),
        ([b"short"], "must be 32 bytes long, got 5"),
        (["not base64!"], "must be base64"),
    ],
)
def test_bad_keys_are_refused(keys: list[bytes | str], reason: str) -> None:
    with pytest.raises(InvalidArgumentError, match=reason):
        _ = SodiumMarshaller(keys)


def test_a_repr_never_shows_the_keys() -> None:
    described = repr(SodiumMarshaller([KEY, OLD_KEY]))

    assert described == "SodiumMarshaller(<2 keys>, DefaultMarshaller())"
    assert KEY not in described


def test_without_the_sodium_extra_it_says_what_to_install(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def without_nacl(
        name: str,
        globals_: Mapping[str, object] | None = None,
        locals_: Mapping[str, object] | None = None,
        fromlist: Sequence[str] = (),
        level: int = 0,
    ) -> object:
        if name.startswith("nacl"):
            raise ImportError(name)
        # The builtin is typed as returning Any; what it returns is a module.
        return cast("object", real_import(name, globals_, locals_, fromlist, level))

    monkeypatch.setattr(builtins, "__import__", without_nacl)

    with pytest.raises(InvalidArgumentError, match=r'install "xtr-cache\[sodium\]"'):
        _ = SodiumMarshaller([KEY])
    with pytest.raises(InvalidArgumentError, match=r'install "xtr-cache\[sodium\]"'):
        _ = SodiumMarshaller.generate_key()


def test_it_is_supported_with_the_sodium_extra_installed() -> None:
    assert SodiumMarshaller.is_supported()


@pytest.mark.usefixtures("nothing_installed")
def test_it_is_not_supported_without_it() -> None:
    assert not SodiumMarshaller.is_supported()


def test_a_generated_key_is_32_random_bytes_in_base64() -> None:
    assert len(base64.b64decode(SodiumMarshaller.generate_key())) == 32
    assert SodiumMarshaller.generate_key() != SodiumMarshaller.generate_key()
