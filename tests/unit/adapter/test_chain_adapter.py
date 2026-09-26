from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from xtr_clock.testing import mock_time

from tests.support.callbacks import Computation
from tests.support.pool_conformance import PoolTests
from xtr_cache import (
    ArrayAdapter,
    ChainAdapter,
    FilesystemAdapter,
    InvalidArgumentError,
    NullAdapter,
)

if TYPE_CHECKING:
    from pathlib import Path


pytestmark = pytest.mark.anyio


class TestChainAdapter(PoolTests):
    @pytest.fixture
    def pool(self, tmp_path: Path) -> ChainAdapter:
        return ChainAdapter([ArrayAdapter(), FilesystemAdapter("pool", directory=tmp_path)])


async def test_a_hit_in_a_slower_pool_fills_the_faster_ones_with_the_life_it_has_left() -> None:
    fast, slow = ArrayAdapter(), ArrayAdapter()
    chain = ChainAdapter([fast, slow])

    with mock_time("2024-04-09 12:00:00") as clock:
        _ = await slow.get("a", Computation("value", lifetime=10))
        clock.sleep(4)

        item = await chain.get_item("a")
        assert item.get() == "value"
        assert (await fast.get_item("a")).get() == "value"

        clock.sleep(6)
        assert not await fast.has_item("a")


async def test_a_value_without_expiry_fills_the_faster_pools_for_the_default_lifetime() -> None:
    fast, slow = ArrayAdapter(), ArrayAdapter()
    chain = ChainAdapter([fast, slow], 5)

    with mock_time("2024-04-09 12:00:00") as clock:
        _ = await slow.save((await slow.get_item("a")).set(1))
        _ = await chain.get_item("a")
        clock.sleep(5)

        assert not await fast.has_item("a")
        assert await slow.has_item("a")


async def test_reading_several_keys_fills_the_faster_pools_with_each_hit() -> None:
    fast, slow = ArrayAdapter(), ArrayAdapter()
    chain = ChainAdapter([fast, slow])
    _ = await fast.save((await fast.get_item("a")).set("fast"))
    _ = await slow.save((await slow.get_item("b")).set("slow"))

    items = await chain.get_items(["a", "b", "c"])

    assert [item.get() for item in items.values()] == ["fast", "slow", None]
    assert (await fast.get_item("b")).get() == "slow"


async def test_writes_deletes_and_clears_reach_every_pool() -> None:
    first, second = ArrayAdapter(), ArrayAdapter()
    chain = ChainAdapter([first, second])

    _ = await chain.save((await chain.get_item("a")).set(1))
    assert await first.has_item("a")
    assert await second.has_item("a")

    assert await chain.delete_item("a")
    assert not await second.has_item("a")

    _ = await chain.save((await chain.get_item("b")).set(1))
    assert await chain.clear()
    assert not await second.has_item("b")


async def test_a_pool_that_holds_a_key_answers_for_the_chain() -> None:
    fast, slow = ArrayAdapter(), ArrayAdapter()
    _ = await slow.save((await slow.get_item("a")).set(1))

    assert await ChainAdapter([fast, slow]).has_item("a")


async def test_pruning_reaches_the_pools_that_prune(tmp_path: Path) -> None:
    files = FilesystemAdapter("pool", directory=tmp_path)
    chain = ChainAdapter([ArrayAdapter(), NullAdapter(), files])

    with mock_time("2024-04-09 12:00:00") as clock:
        _ = await files.save((await files.get_item("a")).set(1).expires_after(1))
        clock.sleep(2)

        assert await chain.prune()

    assert not [path for path in tmp_path.rglob("*") if path.is_file()]


async def test_a_sub_namespace_chains_the_pools_sub_namespaces(tmp_path: Path) -> None:
    files = FilesystemAdapter("pool", directory=tmp_path)
    chain = ChainAdapter([NullAdapter(), files])
    tenant = chain.with_sub_namespace("tenant")

    _ = await tenant.save((await tenant.get_item("a")).set(1))

    assert not await chain.has_item("a")
    assert await files.with_sub_namespace("tenant").has_item("a")
    assert tenant.adapters[0] is chain.adapters[0]


def test_a_chain_needs_a_pool() -> None:
    with pytest.raises(InvalidArgumentError):
        _ = ChainAdapter([])


def test_it_describes_itself() -> None:
    assert repr(ChainAdapter([NullAdapter()], 3)) == "ChainAdapter([NullAdapter()], 3)"


async def test_a_value_saved_with_a_lifetime_is_never_served_past_it_from_a_faster_pool() -> None:
    fast, slow = ArrayAdapter(), ArrayAdapter()
    chain = ChainAdapter([fast, slow])

    with mock_time("2024-04-09 12:00:00") as clock:
        _ = await slow.save((await slow.get_item("a")).set("v").expires_after(10))
        assert (await chain.get_item("a")).get() == "v"

        clock.sleep(10)

        assert not await slow.has_item("a")
        assert not (await chain.get_item("a")).is_hit()


async def test_a_value_stored_under_a_default_lifetime_carries_it_into_faster_pools() -> None:
    fast, slow = ArrayAdapter(), ArrayAdapter(default_lifetime=10)
    chain = ChainAdapter([fast, slow])

    with mock_time("2024-04-09 12:00:00") as clock:
        _ = await slow.save((await slow.get_item("a")).set("v"))
        _ = await chain.get_item("a")
        clock.sleep(10)

        assert not await fast.has_item("a")
