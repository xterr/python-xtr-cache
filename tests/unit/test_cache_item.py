from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from xtr_clock import MockClock
from xtr_clock.testing import mock_time

from xtr_cache import CacheItem, InvalidArgumentError, ItemInterface, LogicError, ValueWrapper


def test_a_miss_holds_nothing_and_a_hit_holds_its_value() -> None:
    miss = CacheItem("k")
    hit = CacheItem("k", 0, hit=True, metadata={"ctime": 3})

    assert (miss.key, miss.get(), miss.is_hit(), miss.metadata) == ("k", None, False, {})
    assert (hit.get(), hit.is_hit(), hit.metadata) == (0, True, {"ctime": 3})
    assert isinstance(hit, ItemInterface)
    assert repr(miss) == "CacheItem('k', miss)"
    assert repr(hit) == "CacheItem('k', hit)"


def test_setting_and_expiring_chain() -> None:
    item = CacheItem("k", clock=MockClock("2024-04-09 12:00:00"))

    same = item.set(1).expires_after(timedelta(seconds=90))

    assert same is item
    assert item.get() == 1
    assert item.expiry == datetime(2024, 4, 9, 12, 1, 30, tzinfo=UTC).timestamp()


def test_an_expiry_is_an_instant_seconds_or_the_pool_default() -> None:
    at = datetime(2030, 1, 1, tzinfo=UTC)
    item = CacheItem("k")

    assert item.expires_at(at).expiry == at.timestamp()
    assert item.expires_at(None).expiry is None
    with mock_time("2024-04-09 12:00:00") as clock:
        assert item.expires_after(5).expiry == clock.now().timestamp() + 5
    assert item.expires_after(None).expiry is None


def test_tags_are_added_once_each_in_order() -> None:
    item = CacheItem("k", taggable=True)

    _ = item.tag("red").tag(["blue", "red"])

    assert item.pending_tags == ("red", "blue")
    assert item.taggable


def test_an_item_of_a_pool_without_tags_refuses_them() -> None:
    with pytest.raises(LogicError, match='Cache item "k" comes from a pool that cannot store tags'):
        _ = CacheItem("k").tag("red")


@pytest.mark.parametrize("tag", ["", "a:b", "a{b}"])
def test_a_tag_that_is_not_a_valid_key_is_refused(tag: str) -> None:
    with pytest.raises(InvalidArgumentError):
        _ = CacheItem("k", taggable=True).tag(tag)


@pytest.mark.parametrize(
    ("key", "reason"),
    [
        (1, "A cache key must be a string, int given."),
        ("", "A cache key must not be empty."),
        ("a@b", 'Cache key "a@b" contains one of the reserved characters "{}()/\\@:".'),
    ],
)
def test_an_invalid_key_is_refused_with_its_reason(key: object, reason: str) -> None:
    with pytest.raises(InvalidArgumentError) as raised:
        _ = CacheItem.validate_key(key)

    assert raised.value.reason == reason


def test_a_valid_key_comes_back_as_it_is() -> None:
    assert CacheItem.validate_key("user.42_a-b") == "user.42_a-b"


def test_an_item_without_metadata_or_expiry_packs_to_its_value() -> None:
    assert CacheItem("k", [1]).pack() == [1]


def test_an_expiring_item_is_packed_with_its_expiry_so_a_chain_can_copy_it() -> None:
    at = datetime(2030, 1, 1, tzinfo=UTC)

    assert CacheItem("k", "v").expires_at(at).pack() == ValueWrapper(
        "v", {"expiry": at.timestamp()}
    )


def test_the_pools_default_expiry_is_packed_when_the_item_sets_none() -> None:
    item = CacheItem("k", "v")

    assert item.pack(default_expiry=99.0) == ValueWrapper("v", {"expiry": 99.0})
    assert item.expires_at(datetime(2030, 1, 1, tzinfo=UTC)).pack(default_expiry=99.0) == (
        ValueWrapper("v", {"expiry": datetime(2030, 1, 1, tzinfo=UTC).timestamp()})
    )


def test_a_recorded_computation_is_packed_with_the_tags_and_expiry() -> None:
    item = CacheItem("k", "v", taggable=True)
    _ = item.tag("red").record_computation(12)

    assert item.pack(default_expiry=99.0) == ValueWrapper(
        "v",
        {"tags": ("red",), "ctime": 12, "expiry": 99.0},
    )


def test_carried_metadata_is_stored_with_the_next_save() -> None:
    item = CacheItem("k", "v").carry_metadata({"ctime": 5, "tags": ["red"], "expiry": 1.0})

    assert item.pack() == ValueWrapper("v", {"ctime": 5, "tags": ("red",)})


def test_a_stored_value_unwraps_into_a_hit_with_its_metadata() -> None:
    wrapped = CacheItem.from_stored("k", ValueWrapper("v", {"ctime": 1}), taggable=True)
    plain = CacheItem.from_stored("k", "v")

    assert (wrapped.get(), wrapped.is_hit(), wrapped.metadata, wrapped.taggable) == (
        "v",
        True,
        {"ctime": 1},
        True,
    )
    assert (plain.get(), plain.is_hit(), plain.metadata) == ("v", True, {})
