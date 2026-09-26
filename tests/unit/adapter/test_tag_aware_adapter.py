from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from xtr_clock.testing import mock_time

from tests.support.callbacks import Computation
from tests.support.pool_conformance import PoolTests
from tests.support.scripted_adapter import ScriptedAdapter
from xtr_cache import (
    ArrayAdapter,
    FilesystemAdapter,
    InvalidArgumentError,
    LogicError,
    NullAdapter,
    TagAwareAdapter,
    TagAwareAdapterInterface,
    TagAwareCacheInterface,
)

if TYPE_CHECKING:
    from pathlib import Path


pytestmark = pytest.mark.anyio


class TestTagAwareAdapter(PoolTests):
    @pytest.fixture
    def pool(self) -> TagAwareAdapter:
        return TagAwareAdapter(ArrayAdapter(), known_tag_versions_ttl=0)


async def _save_tagged(pool: TagAwareAdapter, key: str, *tags: str) -> None:
    _ = await pool.save((await pool.get_item(key)).set(key).tag(list(tags)))


async def test_invalidating_a_tag_drops_every_item_carrying_it_and_only_those() -> None:
    pool = TagAwareAdapter(ArrayAdapter(), known_tag_versions_ttl=0)
    await _save_tagged(pool, "a", "red")
    await _save_tagged(pool, "b", "red", "blue")
    await _save_tagged(pool, "c", "blue")
    _ = await pool.save((await pool.get_item("d")).set("d"))

    assert await pool.invalidate_tags(["red"])

    hits = {key: item.is_hit() for key, item in (await pool.get_items("abcd")).items()}
    assert hits == {"a": False, "b": False, "c": True, "d": True}


async def test_an_item_saved_after_an_invalidation_is_a_hit_again() -> None:
    pool = TagAwareAdapter(ArrayAdapter(), known_tag_versions_ttl=0)
    await _save_tagged(pool, "a", "red")
    _ = await pool.invalidate_tags(["red"])

    await _save_tagged(pool, "a", "red")

    assert (await pool.get_item("a")).is_hit()


async def test_a_deferred_item_takes_its_tags_versions_when_committed() -> None:
    pool = TagAwareAdapter(ArrayAdapter(), known_tag_versions_ttl=0)
    _ = await pool.save_deferred((await pool.get_item("a")).set(1).tag("red"))

    _ = await pool.invalidate_tags(["red"])
    _ = await pool.commit()

    assert (await pool.get_item("a")).is_hit()


async def test_a_hit_reports_its_tags_and_the_callback_can_tag() -> None:
    pool = TagAwareAdapter(ArrayAdapter(), known_tag_versions_ttl=0)

    _ = await pool.get("a", Computation(1, tags=("red", "blue"), lifetime=60))

    item = await pool.get_item("a")
    assert item.metadata.get("tags") == ("red", "blue")
    assert "expiry" in item.metadata
    assert item.taggable


async def test_versions_can_live_in_a_pool_of_their_own(tmp_path: Path) -> None:
    items = ArrayAdapter()
    tags = FilesystemAdapter("tags", directory=tmp_path)
    pool = TagAwareAdapter(items, tags, known_tag_versions_ttl=0)
    await _save_tagged(pool, "a", "red")

    assert [path for path in tmp_path.rglob("*") if path.is_file()]
    assert await tags.clear()
    assert not (await pool.get_item("a")).is_hit()


async def test_versions_read_are_trusted_for_a_while() -> None:
    tags = ArrayAdapter()
    reader = TagAwareAdapter(ArrayAdapter(), tags, known_tag_versions_ttl=5)
    writer = TagAwareAdapter(ArrayAdapter(), tags, known_tag_versions_ttl=0)

    with mock_time("2024-04-09 12:00:00") as clock:
        await _save_tagged(reader, "a", "red")
        _ = await writer.invalidate_tags(["red"])

        assert (await reader.get_item("a")).is_hit()

        clock.sleep(5)
        assert not (await reader.get_item("a")).is_hit()


async def test_a_value_stored_without_tags_underneath_is_a_hit() -> None:
    items = ArrayAdapter()
    _ = await items.save((await items.get_item("plain")).set("value"))

    item = await TagAwareAdapter(items).get_item("plain")

    assert item.get() == "value"


async def test_clearing_everything_clears_the_tags_pool_too() -> None:
    items, tags = ArrayAdapter(), ArrayAdapter()
    pool = TagAwareAdapter(items, tags)
    await _save_tagged(pool, "a", "red")

    assert await pool.clear()

    assert not tags.values()


async def test_a_tag_that_is_not_a_valid_key_is_refused() -> None:
    pool = TagAwareAdapter(ArrayAdapter())

    with pytest.raises(InvalidArgumentError):
        _ = (await pool.get_item("a")).tag("a:b")
    with pytest.raises(InvalidArgumentError):
        _ = await pool.invalidate_tags(["a/b"])
    assert await pool.invalidate_tags([])


async def test_an_item_from_a_pool_without_tags_cannot_be_tagged() -> None:
    with pytest.raises(LogicError, match="cannot store tags"):
        _ = (await ArrayAdapter().get_item("a")).tag("red")


async def test_a_sub_namespace_keeps_items_apart_but_shares_tags() -> None:
    pool = TagAwareAdapter(ArrayAdapter(), known_tag_versions_ttl=0)
    tenant = pool.with_sub_namespace("tenant")
    await _save_tagged(pool, "a", "red")
    await _save_tagged(tenant, "a", "red")

    _ = await pool.invalidate_tags(["red"])

    assert not (await tenant.get_item("a")).is_hit()


async def test_a_sub_namespace_of_a_pool_without_them_is_the_same_items() -> None:
    items = NullAdapter()

    assert TagAwareAdapter(items).with_sub_namespace("t")._items is items


async def test_pruning_and_resetting_reach_the_pools_underneath(tmp_path: Path) -> None:
    files = FilesystemAdapter("items", directory=tmp_path)
    pool = TagAwareAdapter(files, ArrayAdapter())
    _ = await pool.save_deferred((await pool.get_item("a")).set(1))

    await pool.reset()

    assert await files.has_item("a")
    assert await pool.prune()


def test_it_is_tag_aware() -> None:
    pool = TagAwareAdapter(NullAdapter())

    assert isinstance(pool, TagAwareAdapterInterface)
    assert isinstance(pool, TagAwareCacheInterface)
    assert repr(pool) == "TagAwareAdapter(NullAdapter(), NullAdapter())"


async def test_a_new_tag_version_the_tags_pool_did_not_keep_is_not_trusted() -> None:
    tags = ScriptedAdapter()
    tags.fail.add("save")
    pool = TagAwareAdapter(ArrayAdapter(), tags, known_tag_versions_ttl=60)

    await _save_tagged(pool, "a", "red")

    remembered, _ = pool._known["red"]
    assert remembered is None
    assert not (await pool.get_item("a")).is_hit()
