from __future__ import annotations

from xtr_cache import ArrayAdapter, TagAwareAdapter, TagAwareAdapterInterface


def test_a_tag_aware_adapter_satisfies_it() -> None:
    assert isinstance(TagAwareAdapter(ArrayAdapter()), TagAwareAdapterInterface)


def test_an_adapter_without_tags_does_not() -> None:
    assert not isinstance(ArrayAdapter(), TagAwareAdapterInterface)
