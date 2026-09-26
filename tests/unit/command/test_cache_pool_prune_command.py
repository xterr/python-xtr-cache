from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from xtr_clock.testing import mock_time
from xtr_console import ApplicationTester, ExitCode

from xtr_cache import CachePoolClearer, FilesystemAdapter
from xtr_cache.command import use_pools

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.anyio


async def test_the_pools_that_keep_expired_values_are_pruned(
    pools: CachePoolClearer,
    tester: ApplicationTester,
    tmp_path: Path,
) -> None:
    files = await pools.get_pool("files")

    with mock_time("2024-04-09 12:00:00") as clock:
        _ = await files.save((await files.get_item("k")).set(1).expires_after(1))
        clock.sleep(2)

        assert await tester.execute(["cache:pool:prune"]) == ExitCode.SUCCESS

    assert "Pruning cache pool: files" in tester.display
    assert "Pruning cache pool: memory" not in tester.display
    assert "Successfully pruned cache pool(s)." in tester.display
    assert not [path for path in tmp_path.rglob("*") if path.is_file()]


async def test_a_pool_that_fails_to_prune_fails_the_command(
    tester: ApplicationTester,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = FilesystemAdapter("files", directory=tmp_path)

    async def fail() -> bool:
        return False

    monkeypatch.setattr(pool, "prune", fail)
    use_pools(CachePoolClearer({"files": pool}))
    try:
        assert await tester.execute(["cache:pool:prune"]) == ExitCode.FAILURE
    finally:
        use_pools(None)

    assert "Could not prune: files." in tester.display


async def test_without_pools_it_says_how_to_give_them(tester: ApplicationTester) -> None:
    assert await tester.execute(["cache:pool:prune"]) == ExitCode.FAILURE
