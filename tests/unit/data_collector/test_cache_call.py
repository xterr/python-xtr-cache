"""Unit tests for :class:`xtr_cache.data_collector.CacheCall`."""

from __future__ import annotations

import dataclasses

import pytest

from xtr_cache.data_collector import CacheCall


def _call() -> CacheCall:
    return CacheCall(
        pool="app",
        method="get_item",
        keys=("greeting",),
        hits=1,
        misses=0,
        duration_ms=0.5,
        result=None,
    )


def test_a_recorded_call_cannot_be_changed() -> None:
    call = _call()
    field = "hits"  # by name, so the type checkers let the test try what they forbid

    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(call, field, 2)


def test_two_calls_with_the_same_fields_are_equal() -> None:
    assert _call() == _call()
