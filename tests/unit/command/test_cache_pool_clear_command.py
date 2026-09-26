from __future__ import annotations

import pytest
from xtr_console import ApplicationTester, ExitCode

from tests.support.scripted_adapter import ScriptedAdapter
from xtr_cache import CachePoolClearer
from xtr_cache.command import use_pools

pytestmark = pytest.mark.anyio


async def _fill(pools: CachePoolClearer) -> None:
    for name in pools.pool_names():
        pool = await pools.get_pool(name)
        _ = await pool.save((await pool.get_item("k")).set(1))


async def test_the_named_pools_are_cleared(
    pools: CachePoolClearer, tester: ApplicationTester
) -> None:
    await _fill(pools)

    assert await tester.execute(["cache:pool:clear", "memory", "files"]) == ExitCode.SUCCESS

    assert "Clearing cache pool: memory" in tester.display
    assert "Cache was successfully cleared." in tester.display
    assert not await (await pools.get_pool("files")).has_item("k")
    assert await (await pools.get_pool("tagged")).has_item("k")


async def test_all_clears_every_pool_but_the_excluded(
    pools: CachePoolClearer,
    tester: ApplicationTester,
) -> None:
    await _fill(pools)

    code = await tester.execute(["cache:pool:clear", "--all", "--exclude", "tagged"])

    assert code == ExitCode.SUCCESS
    assert not await (await pools.get_pool("memory")).has_item("k")
    assert await (await pools.get_pool("tagged")).has_item("k")


@pytest.mark.usefixtures("pools")
async def test_naming_nothing_or_an_unknown_pool_is_invalid(tester: ApplicationTester) -> None:
    assert await tester.execute(["cache:pool:clear"]) == ExitCode.INVALID
    assert "Name at least one pool" in tester.display

    assert await tester.execute(["cache:pool:clear", "nope"]) == ExitCode.INVALID
    assert 'Unknown cache pool "nope".' in tester.display


async def test_a_pool_that_fails_to_clear_fails_the_command(tester: ApplicationTester) -> None:
    broken = ScriptedAdapter()
    broken.fail.add("clear")
    use_pools(CachePoolClearer({"broken": broken}))
    try:
        assert await tester.execute(["cache:pool:clear", "broken"]) == ExitCode.FAILURE
    finally:
        use_pools(None)

    assert "Could not clear: broken." in tester.display


async def test_without_pools_it_says_how_to_give_them(tester: ApplicationTester) -> None:
    assert await tester.execute(["cache:pool:clear", "--all"]) == ExitCode.FAILURE
    assert "No cache pools" in tester.display
