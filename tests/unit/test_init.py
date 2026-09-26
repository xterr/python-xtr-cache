from __future__ import annotations

import tomllib
from pathlib import Path
from typing import cast

import xtr_cache_contracts

import xtr_cache


def test_the_version_is_the_one_pyproject_declares() -> None:
    pyproject = Path(__file__).parents[2] / "pyproject.toml"
    data = cast(
        "dict[str, dict[str, object]]",
        tomllib.loads(pyproject.read_text(encoding="utf-8")),
    )

    assert xtr_cache.__version__ == data["project"]["version"]


def test_every_exported_name_resolves() -> None:
    assert [name for name in xtr_cache.__all__ if not hasattr(xtr_cache, name)] == []


def test_the_contract_is_re_exported_not_redefined() -> None:
    shared = set(xtr_cache_contracts.__all__) - {"__version__"}

    assert shared <= set(xtr_cache.__all__)
    assert all(getattr(xtr_cache, name) is getattr(xtr_cache_contracts, name) for name in shared)
