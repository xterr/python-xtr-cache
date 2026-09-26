from __future__ import annotations

import threading

import pytest
from xtr_clock.testing import mock_time

from tests.support.pool_conformance import PoolTests
from tests.support.recording_logger import RecordingLogger
from xtr_cache import ArrayAdapter, InvalidArgumentError

pytestmark = pytest.mark.anyio


class TestArrayAdapter(PoolTests):
    @pytest.fixture
    def pool(self) -> ArrayAdapter:
        return ArrayAdapter()


async def test_a_serialized_value_comes_back_as_a_copy() -> None:
    pool = ArrayAdapter()
    stored = [1, 2]
    _ = await pool.save((await pool.get_item("list")).set(stored))
    stored.append(3)

    read = (await pool.get_item("list")).get()

    assert read == [1, 2]
    assert read is not stored


async def test_an_unserialized_value_is_the_object_itself() -> None:
    pool = ArrayAdapter(store_serialized=False)
    stored = [1, 2]
    _ = await pool.save((await pool.get_item("list")).set(stored))

    assert (await pool.get_item("list")).get() is stored


async def test_a_value_that_does_not_serialize_is_not_saved_and_is_logged() -> None:
    pool = ArrayAdapter()
    logger = RecordingLogger()
    pool.set_logger(logger)

    assert not await pool.save((await pool.get_item("lock")).set(threading.Lock()))

    assert not await pool.has_item("lock")
    assert logger.messages("warning") == ['Failed to save key "{key}" of type lock.']


async def test_the_least_recently_used_value_goes_first_beyond_max_items() -> None:
    pool = ArrayAdapter(max_items=2)
    for key in ("a", "b"):
        _ = await pool.save((await pool.get_item(key)).set(key))
    _ = await pool.get_item("a")

    _ = await pool.save((await pool.get_item("c")).set("c"))

    assert set(pool.values()) == {"a", "c"}


async def test_no_value_outlives_max_lifetime() -> None:
    pool = ArrayAdapter(max_lifetime=5)

    with mock_time("2024-04-09 12:00:00") as clock:
        _ = await pool.save((await pool.get_item("a")).set(1))
        _ = await pool.save((await pool.get_item("b")).set(1).expires_after(60))
        clock.sleep(5)

        assert not await pool.has_item("a")
        assert not await pool.has_item("b")


async def test_the_default_lifetime_applies_to_an_item_without_expiry() -> None:
    pool = ArrayAdapter(10)

    with mock_time("2024-04-09 12:00:00") as clock:
        _ = await pool.save((await pool.get_item("a")).set(1))
        clock.sleep(9)
        assert await pool.has_item("a")
        clock.sleep(1)
        assert not await pool.has_item("a")


async def test_values_lists_what_is_live() -> None:
    pool = ArrayAdapter(store_serialized=False)

    with mock_time("2024-04-09 12:00:00") as clock:
        _ = await pool.save((await pool.get_item("a")).set(1))
        _ = await pool.save((await pool.get_item("b")).set(2).expires_after(1))
        clock.sleep(1)

        assert pool.values() == {"a": 1}


async def test_a_stored_value_that_no_longer_reads_is_a_miss() -> None:
    pool = ArrayAdapter()
    pool._values["broken"] = (b"not a pickle", None)

    assert not (await pool.get_item("broken")).is_hit()
    assert "broken" not in pool.values()


def test_a_negative_limit_is_refused() -> None:
    with pytest.raises(InvalidArgumentError, match="max_lifetime"):
        _ = ArrayAdapter(max_lifetime=-1)
    with pytest.raises(InvalidArgumentError, match="max_items"):
        _ = ArrayAdapter(max_items=-1)


def test_it_describes_itself() -> None:
    assert repr(ArrayAdapter(5)) == "ArrayAdapter(5)"
