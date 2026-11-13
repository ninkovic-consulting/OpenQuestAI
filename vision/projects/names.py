"""A project's folder name, and the one folder new projects go in.

The folder name comes from the project's name and nothing else, so it can
hold no path: lowercase ASCII letters and digits in words joined by dashes
(`Photo Date Renamer!` becomes `photo-date-renamer`). Accents are dropped
from their letters (`Café` becomes `cafe`), everything else separates words,
and the name is cut at a word to `MAX_FOLDER_NAME` characters. A name with no
letter or digit gives no folder name and is refused. With no `/`, no `.` and
nothing but `[a-z0-9-]`, the result can only name a folder directly inside
the root.

The root is `[projects] root`, as the owner wrote it. It must be an existing
folder (followed through links), and not the disk, the home folder or a
folder above it: new projects would land beside the owner's own folders.
"""

from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path

from vision.core.config import Config, load_config

MAX_FOLDER_NAME = 48
_NOT_WORD = re.compile(r"[^a-z0-9]+")


class Refused(ValueError):
    """The project cannot be started as asked. The message is for people, and nothing was changed."""


def folder_name(name: str) -> str:
    """The safe folder name for a project name. Raises `Refused` when none can be made."""
    ascii_only = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    words = [w for w in _NOT_WORD.split(ascii_only.lower()) if w]
    out = ""
    for word in words:
        joined = f"{out}-{word}" if out else word
        if len(joined) > MAX_FOLDER_NAME:
            out = out or word[:MAX_FOLDER_NAME]
            break
        out = joined
    if not out:
        raise Refused(
            f"The name {name.strip()!r} has no letters or digits to make a folder name from. "
            "Give the project a name with letters or digits."
        )
    return out


class RootProblem(Refused):
    """`[projects] root` cannot hold new projects; the message is the reason alone."""


def projects_root(root: str) -> Path:
    """The root as a real path, checked. Raises `RootProblem` with the reason."""
    given = root.strip()
    if not given.startswith(("/", "~")):
        raise RootProblem(f"{given or 'An empty path'} is not a full path; start it with / or ~.")
    real = Path(os.path.realpath(Path(given).expanduser()))
    if not real.is_dir():
        raise RootProblem(f"{given} is not a folder on this Mac.")
    home = Path(os.path.realpath(Path.home()))
    if real == Path(real.anchor) or home.is_relative_to(real):
        raise RootProblem(
            f"{given} is the disk, the home folder or a folder above it; new projects need a folder "
            "of their own, such as ~/Projects."
        )
    return real


def saved_root(config: Config) -> str:
    """`[projects] root` as config.toml holds it now, so a change in Settings applies at the
    next call without a restart; the running config's when the file cannot be read."""
    try:
        return load_config(config.paths.home).projects.root
    except (OSError, ValueError):
        return config.projects.root
