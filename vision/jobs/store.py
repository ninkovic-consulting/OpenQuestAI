"""The job board's file, `$VISION_HOME/jobs.json`, private to the user (0600).

A JSON file rather than SQLite, like `automations.json`: the board holds a few
hundred small records at most, keeps them all in memory and writes the whole
list after a change, so a database would add a schema and migrations without
buying anything; the file stays readable by hand and is backed up and reset
with the others. Written through a temporary file and a rename, so a crash
never leaves half a file. A file that cannot be read is moved aside
(`jobs.json.broken`) and the board starts empty. Only the newest
`MAX_ENDED` ended jobs are kept. Blocking; callers use `asyncio.to_thread`.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from vision.core.config import Config
from vision.jobs.model import Job

FILE_NAME = "jobs.json"
VERSION = 1
MAX_ENDED = 200

log = logging.getLogger(__name__)


def path_for(config: Config) -> Path:
    return config.paths.home / FILE_NAME


def load(path: Path) -> list[Job]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [Job.from_dict(item) for item in data["jobs"]]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        broken = path.with_name(path.name + ".broken")
        log.warning("jobs file unreadable (%s); moved to %s", exc, broken)
        path.replace(broken)
        return []


def pruned(jobs: list[Job]) -> list[Job]:
    """Every open job and the newest `MAX_ENDED` ended ones, oldest first."""
    ended = [j for j in jobs if not j.open]
    keep = {id(j) for j in sorted(ended, key=lambda j: j.created_at)[-MAX_ENDED:]}
    return [j for j in jobs if j.open or id(j) in keep]


def save(path: Path, rows: list[dict[str, Any]]) -> None:
    """`rows` are `Job.to_dict()`, made on the event loop so no job changes while it is written."""
    body = json.dumps({"version": VERSION, "jobs": rows}, indent=1, ensure_ascii=False)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(path.name + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(body)
        fh.flush()
        os.fsync(fh.fileno())
    os.chmod(temp, 0o600)
    temp.replace(path)
