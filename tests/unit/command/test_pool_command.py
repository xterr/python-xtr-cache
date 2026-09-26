from __future__ import annotations

import io
from typing import final

from xtr_console import ConsoleStyle

from xtr_cache import ArrayAdapter, CachePoolClearer
from xtr_cache.command.pool_command import PoolCommand


@final
class _Command(PoolCommand):
    __slots__ = ()

    def pools(self, style: ConsoleStyle) -> CachePoolClearer | None:
        return self._pools_or_report(style)


def _style() -> tuple[ConsoleStyle, io.StringIO]:
    output = io.StringIO()
    return ConsoleStyle(output, io.StringIO(), decorated=False, interactive=False), output


def test_a_command_acts_on_the_pools_it_was_given() -> None:
    pools = CachePoolClearer({"app": ArrayAdapter()})
    style, output = _style()

    assert _Command(pools).pools(style) is pools
    assert output.getvalue() == ""


def test_a_command_without_pools_says_how_to_give_them() -> None:
    style, output = _style()

    assert _Command().pools(style) is None
    assert "use_pools()" in output.getvalue()
