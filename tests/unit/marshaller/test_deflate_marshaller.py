from __future__ import annotations

import pickle

from xtr_cache import DefaultMarshaller, DeflateMarshaller


def test_values_are_compressed_and_read_back() -> None:
    marshaller = DeflateMarshaller(DefaultMarshaller())
    value = "x" * 10_000

    encoded, failed = marshaller.marshall({"long": value})

    assert failed == []
    assert len(encoded["long"]) < len(pickle.dumps(value))
    assert marshaller.unmarshall(encoded["long"]) == value


def test_bytes_written_before_compression_are_read_as_they_are() -> None:
    marshaller = DeflateMarshaller(DefaultMarshaller())

    assert marshaller.unmarshall(pickle.dumps([1, 2])) == [1, 2]


def test_it_describes_what_it_wraps() -> None:
    assert repr(DeflateMarshaller(DefaultMarshaller())) == "DeflateMarshaller(DefaultMarshaller())"
