"""Folder names for the project picker, as the user types a path.

Lists only the folder the typed text is in, filtered by the name being typed:
`~/Pro` lists `~` for names starting with `Pro`; `~/Projects/` lists
`~/Projects`. Names only, directories only, no file is ever opened, symlinks
are not followed to decide what is a folder, hidden folders appear only when
the typed name starts with a dot. Paths come back in the form typed.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

MAX_DIRS = 50


class BadPrefix(ValueError):
    """The typed text is not a path this can list. The message is for people."""


def list_dirs(prefix: str, limit: int = MAX_DIRS) -> list[dict[str, Any]]:
    folder, typed = _split(prefix)
    real = Path(folder).expanduser()
    show_hidden = typed.startswith(".")
    wanted = typed.casefold()
    names: list[str] = []
    try:
        with os.scandir(real) as entries:
            for entry in entries:
                name = entry.name
                if name.startswith(".") and not show_hidden:
                    continue
                if not name.casefold().startswith(wanted):
                    continue
                try:
                    if entry.is_dir(follow_symlinks=False):
                        names.append(name)
                except OSError:
                    continue
    except OSError:
        return []
    names.sort(key=lambda n: (n.casefold(), n))
    return [{"name": n, "path": folder + n} for n in names[:limit]]


def _split(prefix: str) -> tuple[str, str]:
    """`~/Pro` -> (`~/`, `Pro`). The folder part always ends with `/`."""
    if prefix == "~":
        prefix = "~/"
    if not prefix.startswith(("/", "~/")):
        raise BadPrefix("Type a full path: start with / or ~/.")
    if "\0" in prefix:
        raise BadPrefix("A path cannot contain a NUL character.")
    head, _, typed = prefix.rpartition("/")
    if ".." in head.split("/") or typed == "..":
        raise BadPrefix("Type the path without '..'.")
    return head + "/", typed
