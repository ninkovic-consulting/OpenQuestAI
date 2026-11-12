"""The scheduler: automations the assistant runs by itself, at set times.

The composition root (`vision.app`) builds `Automations` (the stored list,
in `$VISION_HOME/automations.json`), offers `build_tools(automations)` to the
gate beside the five tools of slice 1, mounts `build_router(automations)`
under `/api`, and once the session runs, starts a `Runner` whose runs go
through `Session.run_automation`.
"""

from __future__ import annotations

from vision.scheduler.runner import Runner
from vision.scheduler.routes import build_router
from vision.scheduler.service import AutomationError, Automations, NotFound
from vision.scheduler.tools import build_tools

__all__ = ["AutomationError", "Automations", "NotFound", "Runner", "build_router", "build_tools"]
