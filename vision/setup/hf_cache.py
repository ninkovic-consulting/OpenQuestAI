"""What is already in the Hugging Face download cache, read from disk only.

No network and no `huggingface_hub` import, so the doctor works without the
optional parts installed.
"""

from __future__ import annotations

import os
from pathlib import Path


def hub_cache() -> Path:
    """The cache folder `huggingface_hub` uses, from the same environment variables."""
    if value := os.environ.get("HF_HUB_CACHE"):
        return Path(value).expanduser()
    if value := os.environ.get("HF_HOME"):
        return Path(value).expanduser() / "hub"
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".cache"
    return base / "huggingface" / "hub"


def cached_size(repo: str, *, needs: str = "*", cache: Path | None = None) -> int | None:
    """Bytes on disk for the newest snapshot of `repo`, or None when it is not downloaded.

    A snapshot only counts when it has at least one file matching `needs`.
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
    # Snapshot entries are symlinks into `blobs/`; `stat` follows them to the real size.
    return sum(f.stat().st_size for f in newest.rglob("*") if f.is_file())


def gigabytes(size: int) -> str:
    return f"{size / 1e9:.1f} GB"
