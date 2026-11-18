"""What the cache panel never shows: a key named like a credential."""

from __future__ import annotations

from typing import Final

__all__ = ["MASK", "masked_key"]

MASK: Final = "******"

_SENSITIVE_WORDS: Final = ("password", "secret", "token", "passwd", "api_key", "apikey")


def masked_key(key: str) -> str:
    """Return ``key``, or the mask when it names a credential.

    A key such as ``reset_token.3f9a…`` often carries the credential itself,
    and a profile is written to disk for anyone with the profiler to read.
    """
    lowered = key.lower()
    return MASK if any(word in lowered for word in _SENSITIVE_WORDS) else key
