from __future__ import annotations

from xtr_cache import CacheError, LogicError


def test_it_carries_the_reason_and_is_a_cache_error() -> None:
    error = LogicError("cannot tag")

    assert error.reason == "cannot tag"
    assert str(error) == "cannot tag"
    assert isinstance(error, CacheError)
