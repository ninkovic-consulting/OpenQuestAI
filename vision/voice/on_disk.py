"""Speech models from this Mac's disk only: nothing here ever downloads.

The owner downloads, keeps and removes models by their own choice (the
download in Settings, Voice; the first-start wizard; `vision setup`; the
doctor's Fix). Every speech load goes through `local_path`, which finds the
model's snapshot folder in the cache by reading the disk, and `mlx-audio`,
handed a folder that exists, loads that folder without asking the Hub.
`huggingface_hub` is not asked: its own offline lookup refuses a snapshot that
lacks any file of the repo, and a working speech download is always such a
snapshot, because only the files that are used get fetched. `require` checks
every part a task needs before anything loads, so a missing part fails at
once with one plain message.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from vision.voice.errors import VoiceUnavailable

WHERE = "Download them in Settings, Voice; nothing is downloaded by itself."


class ModelMissing(VoiceUnavailable):
    """A speech model this task needs is not on this Mac."""


def missing_message(parts: list[str]) -> str:
    return f"The speech models are not downloaded ({', '.join(parts)} missing). {WHERE}"


def missing(parts: Mapping[str, str]) -> list[str]:
    """The parts (by name) whose repo is not in the cache. Reads the disk only."""
    from vision.setup import hf_cache  # here, not at the top: `vision.setup` imports half the daemon

    return [part for part, repo in parts.items() if hf_cache.cached_size(repo) is None]


def require(parts: Mapping[str, str]) -> None:
    """Raise `ModelMissing` naming every part of `parts` that is not downloaded."""
    gone = missing(parts)
    if gone:
        raise ModelMissing(missing_message(gone))


def local_path(repo: str, part: str) -> Path:
    """The cached snapshot of `repo`, never fetched. Raises `ModelMissing` when absent."""
    from vision.setup import hf_cache

    folder = hf_cache.snapshot_path(repo)
    if folder is None:
        raise ModelMissing(missing_message([part]))
    return folder
