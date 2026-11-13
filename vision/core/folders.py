"""Short names for a room's project folders.

With several folders in one room, every path a resident gives the project
tools starts with a folder's short name (`shop-api/src/app.py`). The
workbench resolves those names and the residents' prompt shows them, so
both take them from here and always agree.

A folder's name is the last part of its path as the owner gave it. When
two folders of a room share one (case is ignored, as the Mac's disk does),
the later ones get `-2`, `-3` and so on, in the room's order.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

FALLBACK = "folder"


def folder_names(folders: Sequence[str | Path]) -> list[str]:
    """One short, unique name per folder, in the same order."""
    names: list[str] = []
    taken: set[str] = set()
    for folder in folders:
        base = _own_name(folder)
        name, n = base, 2
        while name.casefold() in taken:
            name, n = f"{base}-{n}", n + 1
        taken.add(name.casefold())
        names.append(name)
    return names


def _own_name(folder: str | Path) -> str:
    """The folder's last path part, cleaned so it can start a path the workbench accepts."""
    name = Path(os.path.normpath(Path(folder).expanduser())).name.lstrip("~")
    name = "".join(ch for ch in name if ch.isprintable())
    return name if name not in ("", ".", "..") else FALLBACK
