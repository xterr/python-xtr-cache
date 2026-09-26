from __future__ import annotations

import pytest
from xtr_console import ApplicationTester, ExitCode

from tests.support.scripted_adapter import ScriptedAdapter
from xtr_cache import CachePoolClearer
from xtr_cache.command import use_pools

pytestmark = pytest.mark.anyio


async def test_an_item_is_deleted(pools: CachePoolClearer, tester: ApplicationTester) -> None:
    pool = await pools.get_pool("memory")
    _ = await pool.save((await pool.get_item("k")).set(1))

    assert await tester.execute(["cache:pool:delete", "memory", "k"]) == ExitCode.SUCCESS

    assert 'Cache item "k" was successfully deleted.' in tester.display
    assert not await pool.has_item("k")


@pytest.mark.usefixtures("pools")
async def test_a_missing_item_is_noted(tester: ApplicationTester) -> None:
    assert await tester.execute(["cache:pool:delete", "memory", "k"]) == ExitCode.SUCCESS
    assert 'Cache item "k" does not exist in cache pool "memory".' in tester.display


@pytest.mark.usefixtures("pools")
async def test_an_unknown_pool_or_a_bad_key_is_invalid(tester: ApplicationTester) -> None:
    assert await tester.execute(["cache:pool:delete", "nope", "k"]) == ExitCode.INVALID
    assert 'Cache pool "nope" not found.' in tester.display

    assert await tester.execute(["cache:pool:delete", "memory", "a:b"]) == ExitCode.INVALID
    assert "reserved characters" in tester.display


async def test_a_delete_that_fails_fails_the_command(tester: ApplicationTester) -> None:
    broken = ScriptedAdapter()
    _ = await broken.save((await broken.get_item("k")).set(1))
    broken.fail.add("delete")
    use_pools(CachePoolClearer({"broken": broken}))
    try:
        assert await tester.execute(["cache:pool:delete", "broken", "k"]) == ExitCode.FAILURE
    finally:
        use_pools(None)

    assert 'Cache item "k" could not be deleted.' in tester.display


async def test_without_pools_it_says_how_to_give_them(tester: ApplicationTester) -> None:
    assert await tester.execute(["cache:pool:delete", "memory", "k"]) == ExitCode.FAILURE
    assert "No cache pools" in tester.display
