from __future__ import annotations

import pickle

from xtr_cache import TaggedValue


def test_it_survives_the_stored_format() -> None:
    tagged = TaggedValue([1, 2], {"red": "abc123"})

    assert pickle.loads(pickle.dumps(tagged)) == tagged  # noqa: S301 — what the test wrote.
