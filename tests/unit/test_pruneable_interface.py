from __future__ import annotations

from typing import TYPE_CHECKING

from xtr_cache import ArrayAdapter, FilesystemAdapter, PruneableInterface

if TYPE_CHECKING:
    from pathlib import Path


def test_a_pool_keeping_expired_values_satisfies_it(tmp_path: Path) -> None:
    assert isinstance(FilesystemAdapter(directory=tmp_path), PruneableInterface)


def test_a_pool_expiring_values_on_its_own_does_not() -> None:
    assert not isinstance(ArrayAdapter(), PruneableInterface)
