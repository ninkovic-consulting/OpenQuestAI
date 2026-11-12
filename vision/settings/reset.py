"""Reset to defaults at three levels, and restore a backup. Both back up first.

- `settings`: config.toml removed (defaults). Applied at once; a restart is
  asked for only when something a restart applies changed (the models, say).
- `house`: house.toml back to the default house; the house reloads at once.
- `everything`: both, plus the memory vault, `log.db`, `budget.json`, the
  automations and the phone channel's settings and pairing (`phone.json`);
  setup counts as not completed again. Memory is closed while its files move
  and opened again on fresh ones, so nothing writes into a backup; a restart
  is still asked for, because the brain keeps the conversation in memory.
  With `remove_key` the Keychain key and the phone's bot token are deleted
  too (never backed up).
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal

from vision import house
from vision.core.config import load_config
from vision.core.events import BudgetUpdate
from vision.remote.store import FILE_NAME as PHONE_FILE
from vision.scheduler.store import FILE_NAME as AUTOMATIONS_FILE
from vision.settings import backups, live
from vision.settings.outside import Outside

if TYPE_CHECKING:
    from vision.app import Daemon

Level = Literal["settings", "house", "everything"]
LOG_ITEMS = ["log.db", "log.db-wal", "log.db-shm"]
NAMES: dict[Level, list[str]] = {
    "settings": ["config.toml"],
    "house": ["house.toml"],
    "everything": [
        "config.toml",
        "house.toml",
        "house",
        *LOG_ITEMS,
        "budget.json",
        AUTOMATIONS_FILE,
        PHONE_FILE,
    ],
}
MEMORY_ITEMS = frozenset({"house", *LOG_ITEMS})
MESSAGES: dict[Level, str] = {
    "settings": "Settings are back to their defaults.",
    "house": "The house is back to the default house.",
    "everything": (
        "Everything is back to a fresh start: settings, house, memory, log, budget, automations "
        "and the phone's pairing."
    ),
}


class Resetter:
    def __init__(self, daemon: Daemon, outside: Callable[[], Outside]) -> None:
        self._daemon = daemon
        self._outside = outside
        self._lock = asyncio.Lock()

    async def reset(self, level: Level, *, remove_key: bool) -> dict[str, Any]:
        async with self._lock:
            names = NAMES[level]
            backup, restart = await self._replace(
                names, lambda: backups.create(self._daemon.config, level, names), lambda: None
            )
            if remove_key and level == "everything":
                await asyncio.to_thread(self._outside().delete_key)
                await self._daemon.phone.forget_token()
            message = MESSAGES[level]
            if remove_key and level == "everything":
                message += " The API key and the phone's bot token were removed from the Keychain."
            if restart:
                message += " Restart the assistant to finish."
            return {"backup": backup.as_dict(), "restart": restart, "message": message}

    async def restore(self, backup_id: str) -> dict[str, Any]:
        """Put a backup's files back, after backing up the current ones. Raises `UnknownBackup`."""
        async with self._lock:
            config = self._daemon.config
            wanted = await asyncio.to_thread(backups.get, config, backup_id)
            backup, restart = await self._replace(
                wanted.files,
                lambda: backups.create(config, "restore", wanted.files),
                lambda: backups.put_back(config, wanted),
            )
            return {"restored": wanted.files, "backup": backup.as_dict(), "restart": restart}

    async def _replace(
        self,
        names: list[str],
        save: Callable[[], backups.Backup],
        refill: Callable[[], object],
    ) -> tuple[backups.Backup, bool]:
        """Back up `names`, remove them, `refill`, then bring the daemon up to date."""
        d = self._daemon
        config = d.config
        memory = MEMORY_ITEMS & set(names)
        if memory:
            await d.components.memory.close()
        try:
            backup = await asyncio.to_thread(save)

            def swap() -> None:
                backups.remove(config, names)
                refill()

            await asyncio.to_thread(swap)
        finally:
            if memory:
                await asyncio.to_thread(house.seed_personas, config)
                await d.components.memory.start()
        restart = bool(memory)
        if "config.toml" in names:
            fresh = await asyncio.to_thread(load_config, config.paths.home)
            restart = restart or live.needs_restart(config, fresh)
            await live.apply(d, fresh)
        if "house.toml" in names and isinstance(d.components.house, live.EditableHouse):
            await d.components.house.reload()
        if "budget.json" in names:
            d.components.budget.reload()
            d.bus.publish(BudgetUpdate(**dataclasses.asdict(d.components.budget.status())))
        if AUTOMATIONS_FILE in names:
            await d.automations.reload()
        if PHONE_FILE in names:
            await d.phone.reload()
        return backup, restart
