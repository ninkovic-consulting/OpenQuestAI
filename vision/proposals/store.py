"""The proposals' file, `$VISION_HOME/proposals.json`, private to the user (0600).

Like `jobs.json`: a few hundred small records held in memory and written whole
after each change, through a temporary file and a rename, so a crash never
leaves half a file. A file that cannot be read is moved aside
(`proposals.json.broken`) and the list starts empty. Every waiting proposal
is kept, and the newest `KEEP_DECIDED` decided ones. Blocking; callers use
`asyncio.to_thread`.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from vision.proposals.model import KEEP_DECIDED, Proposal

FILE_NAME = "proposals.json"
VERSION = 1

log = logging.getLogger(__name__)


def load(path: Path) -> list[Proposal]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [Proposal.from_dict(item) for item in data["proposals"]]
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        broken = path.with_name(path.name + ".broken")
        log.warning("proposals file unreadable (%s); moved to %s", exc, broken)
        path.replace(broken)
        return []


def pruned(proposals: list[Proposal]) -> list[Proposal]:
    """Every waiting proposal and the newest `KEEP_DECIDED` decided ones, in their order."""
    decided = [p for p in proposals if not p.waiting]
    newest = sorted(decided, key=lambda p: p.decided_at or p.created_at)[-KEEP_DECIDED:]
    keep = {p.id for p in newest}
    return [p for p in proposals if p.waiting or p.id in keep]


def save(path: Path, rows: list[dict[str, Any]]) -> None:
    """`rows` are `Proposal.detail()`, made on the event loop so nothing changes while written."""
    write_private(path, json.dumps({"version": VERSION, "proposals": rows}, indent=1, ensure_ascii=False))


def write_private(path: Path, text: str) -> None:
    """Write `text` whole as a 0600 file: a temporary file beside it, then a rename."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise
