"""The automations file, `$VISION_HOME/automations.json`, private to the user (0600).

Written whole on every change, through a temporary file and a rename, so a
crash never leaves half a file. A file that cannot be read is moved aside
(`automations.json.broken`), never overwritten, and the list starts empty.
Blocking; callers use `asyncio.to_thread`.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from vision.core.config import Config
from vision.scheduler.model import Automation

FILE_NAME = "automations.json"
VERSION = 1

log = logging.getLogger(__name__)


def path_for(config: Config) -> Path:
    return config.paths.home / FILE_NAME


def load(path: Path) -> list[Automation]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [Automation.from_dict(item) for item in data["automations"]]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        broken = path.with_name(path.name + ".broken")
        log.warning("automations file unreadable (%s); moved to %s", exc, broken)
        path.replace(broken)
        return []


def save(path: Path, automations: list[Automation]) -> None:
    body = json.dumps(
        {"version": VERSION, "automations": [a.to_dict() for a in automations]},
        indent=2,
        ensure_ascii=False,
    )
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(path.name + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(body)
        fh.flush()
        os.fsync(fh.fileno())
    os.chmod(temp, 0o600)
    temp.replace(path)
