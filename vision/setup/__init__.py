"""Setting Vision up: the requirement checks, `vision doctor` and `vision setup`.

    found = run_checks(config, MacSystem())        # reads only
    print(doctor.as_text(found, "Vision"))
    run_setup(config, MacSystem())                 # asks before every change
"""

from __future__ import annotations

from vision.setup import doctor
from vision.setup.checks import Check, run_checks
from vision.setup.system import MacSystem, System
from vision.setup.wizard import run_setup

__all__ = ["Check", "MacSystem", "System", "doctor", "run_checks", "run_setup"]
