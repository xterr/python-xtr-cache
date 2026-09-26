from __future__ import annotations

import pytest

from xtr_cache import DefaultMarshaller, DeflateMarshaller, MarshallerInterface, SodiumMarshaller


@pytest.mark.parametrize(
    "marshaller",
    [
        DefaultMarshaller(),
        DeflateMarshaller(DefaultMarshaller()),
        SodiumMarshaller([SodiumMarshaller.generate_key()]),
    ],
)
def test_every_marshaller_satisfies_it(marshaller: object) -> None:
    assert isinstance(marshaller, MarshallerInterface)


def test_an_unrelated_object_does_not() -> None:
    assert not isinstance(object(), MarshallerInterface)
