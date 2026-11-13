"""What is already in the Hugging Face download cache, read from disk only.

No network and no `huggingface_hub` import, so the doctor works without the
optional parts installed.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

REPO = re.compile(r"^[A-Za-z0-9][\w.-]{0,95}/[\w.-]{1,95}$")


def hub_cache() -> Path:
    """The cache folder `huggingface_hub` uses, from the same environment variables."""
    if value := os.environ.get("HF_HUB_CACHE"):
        return Path(value).expanduser()
    if value := os.environ.get("HF_HOME"):
        return Path(value).expanduser() / "hub"
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".cache"
    return base / "huggingface" / "hub"


def snapshot_path(repo: str, *, needs: str = "*", cache: Path | None = None) -> Path | None:
    """The folder of the newest snapshot of `repo`, or None when it is not downloaded.

    A snapshot only counts when it has at least one file matching `needs`. It need not
    hold every file of the repo: the speech and chat libraries fetch only the files they
    use, so a working download is a partial snapshot, and `huggingface_hub` itself calls
    such a snapshot incomplete and refuses to return it.
    """
    snapshots = (cache or hub_cache()) / f"models--{repo.replace('/', '--')}" / "snapshots"
    if not snapshots.is_dir():
        return None
    candidates = [s for s in snapshots.iterdir() if s.is_dir()]
    if not candidates:
        return None
    newest = max(candidates, key=lambda s: s.stat().st_mtime)
    if not any(f.is_file() for f in newest.rglob(needs)):
        return None
    return newest


def cached_size(repo: str, *, needs: str = "*", cache: Path | None = None) -> int | None:
    """Bytes on disk for the newest snapshot of `repo`, or None when it is not downloaded."""
    newest = snapshot_path(repo, needs=needs, cache=cache)
    if newest is None:
        return None
    # Snapshot entries are symlinks into `blobs/`; `stat` follows them to the real size.
    return sum(f.stat().st_size for f in newest.rglob("*") if f.is_file())


def repo_folder(repo: str, cache: Path | None = None) -> Path:
    """The cache folder of `repo`. Raises ValueError for anything that is not `owner/name`."""
    if not REPO.match(repo) or ".." in repo:
        raise ValueError(f"{repo!r} is not a Hugging Face repo id.")
    return (cache or hub_cache()) / f"models--{repo.replace('/', '--')}"


def delete(repo: str, cache: Path | None = None) -> int:
    """Remove `repo` from the cache, every snapshot and blob; returns the bytes freed."""
    folder = repo_folder(repo, cache)
    if not folder.is_dir():
        return 0
    freed = sum(f.stat().st_size for f in folder.rglob("*") if f.is_file() and not f.is_symlink())
    shutil.rmtree(folder)
    return freed


def gigabytes(size: int) -> str:
    return f"{size / 1e9:.1f} GB"
