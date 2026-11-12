"""Reading and writing house files."""

from __future__ import annotations

import os
import shutil
import tempfile
import tomllib
from pathlib import Path
from typing import Any

import tomli_w

from vision.core import resources
from vision.house.model import HouseError

DEFAULT_FILE = resources.house_dir() / "default.toml"
AGENTS_DIR = DEFAULT_FILE.parent / "agents"

Stamp = tuple[int, int]
"""A file's (modification time in ns, size), to notice hand edits."""


def read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise HouseError(f"{path.name} is not valid TOML: {exc}.") from exc


def stamp(path: Path) -> Stamp | None:
    try:
        st = path.stat()
    except FileNotFoundError:
        return None
    return st.st_mtime_ns, st.st_size


def ensure_user_file(path: Path, default: Path) -> None:
    """Create the user's house file as a copy of the default, keeping its comments."""
    if not path.exists():
        _write_atomic(path, default.read_bytes())


def seed_personas(vault: Path, source: Path = AGENTS_DIR) -> None:
    """Copy the repo's agent personas into `<vault>/agents/`, never overwriting one."""
    target = vault / "agents"
    target.mkdir(parents=True, exist_ok=True)
    for persona in sorted(source.glob("*.md")):
        dest = target / persona.name
        if not dest.exists():
            shutil.copyfile(persona, dest)


def write_toml(path: Path, doc: dict[str, Any]) -> Stamp | None:
    """Replace the file atomically and return its new stamp."""
    _write_atomic(path, tomli_w.dumps(doc).encode())
    return stamp(path)


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
