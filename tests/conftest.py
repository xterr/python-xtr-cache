"""Shared test fixtures. No test reaches a server: Redis is a fake kept in memory."""

from __future__ import annotations

import importlib.util
from typing import TYPE_CHECKING

import pytest
from xtr_clock import Clock

if TYPE_CHECKING:
    from collections.abc import Generator


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def nothing_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every optional library look uninstalled to whoever asks ``find_spec``."""

    def find_nothing(name: str) -> None:
        del name

    monkeypatch.setattr(importlib.util, "find_spec", find_nothing)


@pytest.fixture(autouse=True)
def _isolate_clock() -> Generator[None, None, None]:
    """Keep a test that installs a clock from reaching the next one."""
    with Clock.using(Clock.get()):
        yield
