from __future__ import annotations

import threading
from dataclasses import dataclass

import pytest
from typing_extensions import override

from xtr_cache import DefaultMarshaller, MarshallerInterface, MarshallingError


@dataclass(frozen=True)
class Order:
    id: int
    lines: tuple[str, ...]


def test_any_value_that_pickles_round_trips_as_its_own_type() -> None:
    marshaller = DefaultMarshaller()

    encoded, failed = marshaller.marshall({"order": Order(1, ("a",)), "none": None})

    assert failed == []
    assert marshaller.unmarshall(encoded["order"]) == Order(1, ("a",))
    assert marshaller.unmarshall(encoded["none"]) is None


def test_a_value_that_does_not_pickle_is_reported_and_the_rest_encoded() -> None:
    encoded, failed = DefaultMarshaller().marshall({"lock": threading.Lock(), "ok": 1})

    assert failed == ["lock"]
    assert set(encoded) == {"ok"}


def test_bytes_that_are_not_a_pickle_are_refused() -> None:
    with pytest.raises(MarshallingError, match="cannot be unpickled"):
        _ = DefaultMarshaller().unmarshall(b"garbage")


def test_it_is_a_marshaller() -> None:
    assert isinstance(DefaultMarshaller(), MarshallerInterface)
    assert repr(DefaultMarshaller()) == "DefaultMarshaller()"


class _UnprintableError(Exception):
    @override
    def __str__(self) -> str:
        raise ValueError("cannot say")


def _refuse_to_rebuild() -> object:
    raise _UnprintableError


class _RebuildsBadly:
    """Pickles fine; unpickling runs code that fails with an error that cannot say what it is."""

    @override
    def __reduce__(self) -> tuple[object, tuple[()]]:
        return (_refuse_to_rebuild, ())


def test_an_unprintable_unpickling_error_is_named_by_its_class() -> None:
    encoded, _ = DefaultMarshaller().marshall({"bad": _RebuildsBadly()})

    with pytest.raises(MarshallingError, match=r"\[unprintable .*_UnprintableError\]"):
        _ = DefaultMarshaller().unmarshall(encoded["bad"])
