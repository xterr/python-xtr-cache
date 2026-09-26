from __future__ import annotations

import pickle

from xtr_cache import ValueWrapper


def test_it_survives_the_stored_format() -> None:
    wrapped = ValueWrapper({"a": 1}, {"expiry": 2.0, "ctime": 3})

    assert pickle.loads(pickle.dumps(wrapped)) == wrapped  # noqa: S301 — what the test wrote.
