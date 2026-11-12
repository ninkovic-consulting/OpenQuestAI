"""Find a program on this Mac even when `PATH` is short.

The daemon runs under launchd with a minimal `PATH`, so a lookup there would
miss tools installed by Homebrew, nvm, Docker Desktop or an app bundle. This
looks in `PATH` first, then in the usual places those installers use.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def search_dirs(home: Path | None = None) -> list[Path]:
    """Places to look after `PATH`, most likely first."""
    home = home or Path.home()
    dirs = [
        Path("/opt/homebrew/bin"),
        Path("/opt/homebrew/sbin"),
        Path("/usr/local/bin"),
        home / ".local" / "bin",
        home / ".cargo" / "bin",
        home / ".volta" / "bin",
        home / ".bun" / "bin",
        home / ".docker" / "bin",
        Path("/Applications/Docker.app/Contents/Resources/bin"),
        Path("/Applications/Tailscale.app/Contents/MacOS"),
        Path("/Applications/Godot.app/Contents/MacOS"),
        Path("/Applications/Unity Hub.app/Contents/MacOS"),
        Path("/usr/bin"),
        Path("/bin"),
    ]
    nvm = home / ".nvm" / "versions" / "node"
    if nvm.is_dir():
        versions = sorted(nvm.iterdir(), key=lambda p: _version_key(p.name), reverse=True)
        dirs[3:3] = [v / "bin" for v in versions]
    return dirs


def find_program(name: str, *, path: str | None = None, home: Path | None = None) -> Path | None:
    """The program's full path, or None when it is not installed anywhere known."""
    found = shutil.which(name, path=path if path is not None else os.environ.get("PATH", ""))
    if found:
        return Path(found)
    extra = os.pathsep.join(str(d) for d in search_dirs(home))
    found = shutil.which(name, path=extra)
    return Path(found) if found else None


def _version_key(name: str) -> tuple[int, ...]:
    parts = name.lstrip("v").split(".")
    return tuple(int(p) if p.isdigit() else 0 for p in parts)
