"""The settings screen's daemon side: `/api/settings` and its neighbours.

    service = SettingsService(daemon)          # MacOutside unless one is given
    app.include_router(build_router(service), prefix="/api", dependencies=auth)

The HTTP contract is in the settings contract shared with the window. Changes
apply at once where the daemon can (the name, the cap, gate tiers, agents,
voice); model changes are saved and listed in `restart_pending`.
"""

from __future__ import annotations

from vision.settings.outside import MacOutside, Outside
from vision.settings.routes import build_router
from vision.settings.service import SettingsService

__all__ = ["MacOutside", "Outside", "SettingsService", "build_router"]
