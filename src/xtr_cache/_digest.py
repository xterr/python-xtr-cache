"""A short, key-safe digest of a text, for what the pools store under names derived from it."""

from __future__ import annotations

import base64
import hashlib

__all__ = ["urlsafe_digest"]


def urlsafe_digest(text: str, *, size: int = 32) -> str:
    """Return the first ``size`` bytes of ``text``'s SHA-256, in URL-safe base64 without padding.

    Stored identifiers and file names are made from it: its output must never
    change, or what was stored could no longer be found.
    """
    digest = hashlib.sha256(text.encode()).digest()[:size]
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")
