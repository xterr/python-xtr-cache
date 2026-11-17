"""The package and its adapters import without the container, which is not a dependency.

The dev group installs the container, so nothing else in this suite can
express its absence: a fresh interpreter with it blanked out can.
"""

from __future__ import annotations

import subprocess
import sys

_SCRIPT = (
    "import sys; "
    "sys.modules['xtr_dependency_injection'] = None; "
    "sys.modules['xtr_service_contracts'] = None; "
    "import xtr_cache, xtr_cache.adapter"
)


def test_it_imports_without_the_container() -> None:
    completed = subprocess.run(  # noqa: S603 — the program is a fixed literal, not user input
        [sys.executable, "-c", _SCRIPT], capture_output=True, text=True, check=False
    )

    assert completed.returncode == 0, completed.stderr
