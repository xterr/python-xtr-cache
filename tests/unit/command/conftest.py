"""The cache commands run without a container, on pools given with ``use_pools``."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from xtr_console import Application, ApplicationTester

from xtr_cache import ArrayAdapter, CachePoolClearer, FilesystemAdapter, TagAwareAdapter
from xtr_cache.command import use_pools

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


@pytest.fixture
def pools(tmp_path: Path) -> Generator[CachePoolClearer, None, None]:
    """Three pools — in memory, on disk, tag-aware — for every cache command to act on."""
    clearer = CachePoolClearer(
        {
            "memory": ArrayAdapter(),
            "files": FilesystemAdapter("files", directory=tmp_path),
            "tagged": TagAwareAdapter(ArrayAdapter(), known_tag_versions_ttl=0),
        },
    )
    use_pools(clearer)
    yield clearer
    use_pools(None)


@pytest.fixture
def tester() -> ApplicationTester:
    return ApplicationTester(Application("test", catch_exceptions=False))
