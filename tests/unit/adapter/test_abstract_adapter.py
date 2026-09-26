from __future__ import annotations

from typing import ClassVar, final

import pytest
from typing_extensions import override
from xtr_clock.testing import mock_time

from tests.support.recording_logger import RecordingLogger
from tests.support.scripted_adapter import ScriptedAdapter
from xtr_cache import AbstractAdapter, ArrayAdapter, CacheItem, InvalidArgumentError

pytestmark = pytest.mark.anyio


def _logged(pool: AbstractAdapter) -> RecordingLogger:
    logger = RecordingLogger()
    pool.set_logger(logger)
    return logger


async def test_a_backend_failing_to_read_is_a_logged_miss() -> None:
    pool = ScriptedAdapter("ns")
    logger = _logged(pool)
    _ = await pool.save((await pool.get_item("a")).set(1))
    pool.fail.update({"fetch", "have"})

    assert not (await pool.get_item("a")).is_hit()
    assert [item.is_hit() for item in (await pool.get_items(["a"])).values()] == [False]
    assert not await pool.has_item("a")
    assert logger.messages("warning") == [
        'Failed to fetch key "{key}": {reason}',
        "Failed to fetch items: {reason}",
        'Failed to check if key "{key}" is cached: {reason}',
    ]
    _, _, context = logger.records[0]
    assert context["key"] == "a"
    assert context["cache_adapter"] == "ScriptedAdapter"
    assert context["reason"] == "fetch"


async def test_a_backend_failing_to_clear_reports_false() -> None:
    pool = ScriptedAdapter()
    logger = _logged(pool)
    pool.fail.add("clear")

    assert not await pool.clear()
    assert logger.messages("warning") == ["Failed to clear the cache: {reason}"]


async def test_clearing_a_prefix_clears_under_the_namespace() -> None:
    pool = ScriptedAdapter("ns")

    assert await pool.clear("user.")

    assert pool.calls == [("clear", ("ns:user.",))]


async def test_a_batch_delete_refused_is_retried_one_key_at_a_time() -> None:
    pool = ScriptedAdapter()
    pool.refuse_batches = True

    assert await pool.delete_items(["a", "b"])

    assert pool.calls == [("delete", ("a", "b")), ("delete", ("a",)), ("delete", ("b",))]


async def test_a_delete_failing_for_one_key_is_logged_and_reported() -> None:
    pool = ScriptedAdapter()
    logger = _logged(pool)
    pool.fail.add("delete")

    assert not await pool.delete_items(["a"])
    assert logger.messages("warning") == ['Failed to delete key "{key}": {reason}']


async def test_a_delete_refused_for_one_key_is_logged_and_reported() -> None:
    pool = ScriptedAdapter()
    logger = _logged(pool)
    pool.refuse_all = True

    assert not await pool.delete_items(["a", "b"])
    assert logger.messages("warning") == ['Failed to delete key "{key}".'] * 2


async def test_a_batch_save_refused_is_retried_one_value_at_a_time() -> None:
    pool = ScriptedAdapter()
    pool.refuse_batches = True
    for key in ("a", "b"):
        _ = await pool.save_deferred((await pool.get_item(key)).set(key))

    assert await pool.commit()

    assert set(pool.stored) == {"a", "b"}


async def test_values_the_backend_rejects_are_logged_and_reported() -> None:
    pool = ScriptedAdapter()
    logger = _logged(pool)
    pool.reject.add("b")
    for key in ("a", "b"):
        _ = await pool.save_deferred((await pool.get_item(key)).set(key))

    assert not await pool.commit()

    assert logger.messages("warning") == ['Failed to save key "{key}" of type str.']


async def test_a_save_raising_is_logged_with_its_reason() -> None:
    pool = ScriptedAdapter()
    logger = _logged(pool)
    pool.fail.add("save")

    assert not await pool.save((await pool.get_item("a")).set(1))

    assert logger.messages("warning") == ['Failed to save key "{key}" of type int: {reason}']


async def test_a_batch_raising_is_retried_and_each_failure_logged() -> None:
    pool = ScriptedAdapter()
    logger = _logged(pool)
    pool.fail.add("save")
    for key in ("a", "b"):
        _ = await pool.save_deferred((await pool.get_item(key)).set(key))

    assert not await pool.commit()

    assert len(logger.messages("warning")) == 2


async def test_items_are_saved_in_one_batch_per_lifetime() -> None:
    pool = ScriptedAdapter()

    with mock_time("2024-04-09 12:00:00"):
        for key, ttl in (("a", 10), ("b", 10), ("c", 20)):
            _ = await pool.save_deferred((await pool.get_item(key)).set(1).expires_after(ttl))
        _ = await pool.save_deferred((await pool.get_item("gone")).set(1).expires_after(-1))

        assert await pool.commit()

    writes = [call for call in pool.calls if call[0] != "fetch"]
    assert writes == [
        ("delete", ("gone",)),
        ("save", ("a", "b")),
        ("save", ("c",)),
    ]


async def test_expired_items_that_cannot_be_deleted_fail_the_commit() -> None:
    pool = ScriptedAdapter()
    logger = _logged(pool)
    pool.fail.add("delete")
    _ = await pool.save_deferred((await pool.get_item("gone")).set(1).expires_after(0))

    assert not await pool.commit()
    assert logger.messages("warning") == ["Failed to delete expired items: {reason}"]


async def test_committing_nothing_touches_nothing() -> None:
    pool = ScriptedAdapter()

    assert await pool.commit()
    await pool.reset()

    assert pool.calls == []


@pytest.mark.parametrize(
    ("namespace", "message"),
    [
        ("a::b", "empty sub-namespace"),
        ("a/b", "reserved characters"),
    ],
)
def test_a_namespace_that_is_not_a_valid_key_is_refused(namespace: str, message: str) -> None:
    with pytest.raises(InvalidArgumentError, match=message):
        _ = ScriptedAdapter(namespace)


def test_a_namespace_may_hold_sub_namespaces() -> None:
    assert ScriptedAdapter("app:tenant").namespace == "app:tenant:"


@final
class _ShortIds(AbstractAdapter):
    max_id_length: ClassVar[int | None] = 40

    @override
    async def _do_fetch(self, ids: object) -> dict[str, object]:
        return {}

    @override
    async def _do_have(self, id_: str) -> bool:
        return False

    @override
    async def _do_clear(self, namespace: str) -> bool:
        return True

    @override
    async def _do_delete(self, ids: object) -> bool:
        return True

    @override
    async def _do_save(self, values: object, lifetime: float) -> bool:
        return True


def test_a_key_too_long_for_the_backend_is_hashed_under_the_namespace() -> None:
    pool = _ShortIds("ns")

    short = pool._get_id("short")
    long = pool._get_id("k" * 100)

    assert short == "ns:short"
    assert long.startswith("ns:")
    assert len(long) <= 40
    assert long != pool._get_id("k" * 101)


def test_a_namespace_leaving_no_room_for_keys_is_refused() -> None:
    with pytest.raises(InvalidArgumentError, match="16 characters at most"):
        _ = _ShortIds("n" * 17)


async def test_a_sub_namespace_starts_with_nothing_deferred() -> None:
    pool = ArrayAdapter()
    _ = await pool.save_deferred((await pool.get_item("a")).set(1))

    tenant = pool.with_sub_namespace("tenant")

    assert tenant.namespace == "tenant:"
    assert not await tenant.has_item("a")
    assert await pool.has_item("a")


async def test_the_default_lifetime_is_known() -> None:
    assert ScriptedAdapter(default_lifetime=5).default_lifetime == 5


async def test_an_item_read_is_a_cache_item() -> None:
    assert isinstance(await ScriptedAdapter().get_item("a"), CacheItem)
