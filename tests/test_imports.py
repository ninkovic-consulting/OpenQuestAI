"""Every package imports on its own, in a fresh interpreter.

The daemon imports things in one order and the commands (`vision doctor`,
`python -m vision.voice.devices`) in others. A loop between two packages can
work in the first order and crash in the second, so each package is imported
alone here, the way a command would reach it.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

PACKAGES = [
    "vision",
    "vision.app",
    "vision.aware",
    "vision.brains",
    "vision.core.cli",
    "vision.core.server",
    "vision.gate",
    "vision.house",
    "vision.jobs",
    "vision.macapp",
    "vision.memory",
    "vision.presence",
    "vision.projects",
    "vision.remote",
    "vision.residents",
    "vision.scheduler",
    "vision.settings",
    "vision.setup",
    "vision.voice",
    "vision.voice.devices",
    "vision.voice.on_disk",
    "vision.workbench",
]


@pytest.mark.parametrize("package", PACKAGES)
def test_a_package_imports_on_its_own(package: str) -> None:
    done = subprocess.run(
        [sys.executable, "-c", f"import {package}"], capture_output=True, text=True, timeout=120, check=False
    )
    assert done.returncode == 0, done.stderr.strip().splitlines()[-1] if done.stderr.strip() else "no output"
