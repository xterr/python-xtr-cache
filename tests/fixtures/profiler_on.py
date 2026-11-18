"""Turns the http kernel's profiler on, keeping profiles where the test says."""

from __future__ import annotations

import os

from xtr_dependency_injection import configure
from xtr_http_kernel.bundle import HttpKernelConfig, ProfilerConfig


@configure
def http_kernel() -> HttpKernelConfig:
    return HttpKernelConfig(
        profiler=ProfilerConfig(enabled=True, storage_path=os.environ.get("PROFILER_TEST_FOLDER"))
    )
