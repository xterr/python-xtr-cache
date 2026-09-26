from __future__ import annotations

import pytest
from xtr_console import ApplicationTester, ExitCode

pytestmark = pytest.mark.anyio


@pytest.mark.usefixtures("pools")
async def test_every_pool_is_listed_by_name(tester: ApplicationTester) -> None:
    assert await tester.execute(["cache:pool:list"]) == ExitCode.SUCCESS

    assert "Pool name" in tester.display
    for name in ("files", "memory", "tagged"):
        assert name in tester.display


async def test_without_pools_it_says_how_to_give_them(tester: ApplicationTester) -> None:
    assert await tester.execute(["cache:pool:list"]) == ExitCode.FAILURE
