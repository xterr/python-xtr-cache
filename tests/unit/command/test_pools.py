from __future__ import annotations

from xtr_cache import ArrayAdapter, CachePoolClearer
from xtr_cache.command import use_pools
from xtr_cache.command.pools import UNSET, resolve_pools


def test_pools_a_command_was_given_win() -> None:
    given = CachePoolClearer({"app": ArrayAdapter()})
    use_pools(CachePoolClearer())
    try:
        assert resolve_pools(given) is given
    finally:
        use_pools(None)


def test_without_given_pools_the_ones_set_for_the_process_are_used() -> None:
    process = CachePoolClearer({"app": ArrayAdapter()})
    use_pools(process)
    try:
        assert resolve_pools(UNSET) is process
    finally:
        use_pools(None)


def test_with_neither_there_are_none() -> None:
    assert resolve_pools(UNSET) is None
