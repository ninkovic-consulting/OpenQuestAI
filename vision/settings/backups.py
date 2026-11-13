"""Backups of the user's files under `$VISION_HOME/backups/<id>/`, with a `manifest.json`.

A backup holds copies of some of these items, by name: `config.toml`,
`house.toml`, `house` (the memory vault), `log.db` with its `-wal` and `-shm`
files, `budget.json`, `automations.json`, `jobs.json` and `phone.json`. The API key and the
phone's bot token are never among them. Nothing here
decides what to reset; `reset.py` does.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from vision.brains.budget import FILE_NAME as BUDGET_FILE
from vision.core.config import Config
from vision.jobs.store import FILE_NAME as JOBS_FILE
from vision.remote.store import FILE_NAME as PHONE_FILE
from vision.scheduler.store import FILE_NAME as AUTOMATIONS_FILE

MANIFEST = "manifest.json"
LEVELS = ("settings", "house", "everything", "restore")
ID = re.compile(r"^\d{8}-\d{6}-(?:settings|house|everything|restore)(?:-\d{1,3})?$")


class UnknownBackup(LookupError):
    def __init__(self, backup_id: str) -> None:
        super().__init__(f"There is no backup called {backup_id!r}.")


@dataclass(frozen=True, slots=True)
class Backup:
    id: str
    created_at: float
    level: str
    files: list[str]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def items(config: Config) -> dict[str, Path]:
    """Every item a backup may hold, by name, and where it lives."""
    log_db = config.paths.log_db
    return {
        "config.toml": config.paths.config_file,
        "house.toml": config.paths.house_file,
        "house": config.paths.house,
        "log.db": log_db,
        "log.db-wal": log_db.with_name(log_db.name + "-wal"),
        "log.db-shm": log_db.with_name(log_db.name + "-shm"),
        "budget.json": config.paths.home / BUDGET_FILE,
        AUTOMATIONS_FILE: config.paths.home / AUTOMATIONS_FILE,
        JOBS_FILE: config.paths.home / JOBS_FILE,
        PHONE_FILE: config.paths.home / PHONE_FILE,
    }


def folder(config: Config) -> Path:
    return config.paths.home / "backups"


def create(config: Config, level: str, names: list[str], now: float | None = None) -> Backup:
    """Copy the named items that exist into a new backup. Raises before anything is lost."""
    created = time.time() if now is None else now
    root = folder(config)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    base = f"{time.strftime('%Y%m%d-%H%M%S', time.localtime(created))}-{level}"
    backup_id, n = base, 2
    while (root / backup_id).exists():
        backup_id, n = f"{base}-{n}", n + 1
    target = root / backup_id
    target.mkdir(mode=0o700)
    where = items(config)
    copied: list[str] = []
    for name in names:
        source = where[name]
        if source.is_dir():
            shutil.copytree(source, target / name, symlinks=True)
        elif source.is_file():
            shutil.copy2(source, target / name)
        else:
            continue
        copied.append(name)
    backup = Backup(backup_id, created, level, copied)
    _write_manifest(target / MANIFEST, backup)
    return backup


def list_all(config: Config) -> list[Backup]:
    """Every readable backup, newest first."""
    root = folder(config)
    if not root.is_dir():
        return []
    found = []
    for entry in root.iterdir():
        if ID.match(entry.name):
            try:
                found.append(get(config, entry.name))
            except UnknownBackup:
                continue
    return sorted(found, key=lambda b: (b.created_at, b.id), reverse=True)


def get(config: Config, backup_id: str) -> Backup:
    """One backup by id. Ids are checked by pattern first, so no path can escape the folder."""
    if not ID.match(backup_id):
        raise UnknownBackup(backup_id)
    path = folder(config) / backup_id / MANIFEST
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        files = [str(f) for f in data["files"]]
        backup = Backup(backup_id, float(data["created_at"]), str(data["level"]), files)
    except (OSError, ValueError, KeyError, TypeError):
        raise UnknownBackup(backup_id) from None
    if backup.level not in LEVELS or not set(files) <= set(items(config)):
        raise UnknownBackup(backup_id)
    return backup


def remove(config: Config, names: list[str]) -> None:
    """Delete the named items. Call only after `create` has copied them."""
    where = items(config)
    for name in names:
        path = where[name]
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        elif path.exists() or path.is_symlink():
            path.unlink()


def put_back(config: Config, backup: Backup) -> list[str]:
    """Replace the items the backup holds with its copies. Back them up first."""
    source = folder(config) / backup.id
    where = items(config)
    remove(config, backup.files)
    for name in backup.files:
        target = where[name]
        target.parent.mkdir(parents=True, exist_ok=True)
        if (source / name).is_dir():
            shutil.copytree(source / name, target, symlinks=True)
        else:
            shutil.copy2(source / name, target)
    return list(backup.files)


def _write_manifest(path: Path, backup: Backup) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(backup.as_dict(), fh, indent=2)
