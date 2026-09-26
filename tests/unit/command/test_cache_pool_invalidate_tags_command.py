from __future__ import annotations

import pytest
from xtr_console import ApplicationTester, ExitCode

from tests.support.scripted_adapter import ScriptedAdapter
from xtr_cache import ArrayAdapter, CachePoolClearer, TagAwareAdapter
from xtr_cache.command import use_pools

pytestmark = pytest.mark.anyio


async def _tagged(pools: CachePoolClearer) -> TagAwareAdapter:
    pool = await pools.get_pool("tagged")
    assert isinstance(pool, TagAwareAdapter)
    _ = await pool.save((await pool.get_item("k")).set(1).tag("red"))
    return pool


async def test_tags_are_invalidated_in_every_tag_aware_pool(
    pools: CachePoolClearer,
    tester: ApplicationTester,
) -> None:
    pool = await _tagged(pools)

    assert await tester.execute(["cache:pool:invalidate-tags", "red"]) == ExitCode.SUCCESS

    assert 'Invalidated tags in cache pool "tagged".' in tester.display
    assert "Successfully invalidated cache tags." in tester.display
    assert not await pool.has_item("k")


async def test_tags_are_invalidated_in_the_pools_named(
    pools: CachePoolClearer,
    tester: ApplicationTester,
) -> None:
    pool = await _tagged(pools)

    assert await tester.execute(["cache:pool:invalidate-tags", "red", "-p", "tagged"]) == 0

    assert not await pool.has_item("k")


@pytest.mark.usefixtures("pools")
async def test_a_named_pool_that_is_not_tag_aware_is_an_error(tester: ApplicationTester) -> None:
    code = await tester.execute(["cache:pool:invalidate-tags", "red", "--pool", "memory"])

    assert code == ExitCode.FAILURE
    assert 'Cache pool "memory" is not tag-aware.' in tester.display


@pytest.mark.usefixtures("pools")
async def test_no_tag_or_an_unknown_pool_or_a_bad_tag_is_invalid(tester: ApplicationTester) -> None:
    assert await tester.execute(["cache:pool:invalidate-tags"]) == ExitCode.INVALID
    assert await tester.execute(["cache:pool:invalidate-tags", "red", "-p", "nope"]) == 2
    assert await tester.execute(["cache:pool:invalidate-tags", "a:b"]) == ExitCode.INVALID


async def test_without_a_tag_aware_pool_there_is_nothing_to_do(tester: ApplicationTester) -> None:
    use_pools(CachePoolClearer({"memory": ArrayAdapter()}))
    try:
        assert await tester.execute(["cache:pool:invalidate-tags", "red"]) == ExitCode.SUCCESS
    finally:
        use_pools(None)

    assert "No tag-aware cache pool" in tester.display


async def test_an_invalidation_that_fails_fails_the_command(tester: ApplicationTester) -> None:
    tags = ScriptedAdapter()
    tags.fail.add("delete")
    use_pools(CachePoolClearer({"tagged": TagAwareAdapter(ArrayAdapter(), tags)}))
    try:
        assert await tester.execute(["cache:pool:invalidate-tags", "red"]) == ExitCode.FAILURE
    finally:
        use_pools(None)

    assert 'Cache tags could not be invalidated in pool "tagged".' in tester.display


async def test_without_pools_it_says_how_to_give_them(tester: ApplicationTester) -> None:
    assert await tester.execute(["cache:pool:invalidate-tags", "red"]) == ExitCode.FAILURE
