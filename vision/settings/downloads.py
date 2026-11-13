"""The local model and the speech models, downloaded in the background.

Progress is measured on disk: the bytes in the Hugging Face cache folder of
each repo (`blobs/`, `.incomplete` files included). The total is the real size
when the Hub answers, else an estimate.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, get_args

from vision.core.config import Config
from vision.settings.outside import Outside
from vision.setup import hf_cache
from vision.voice.settings import VoiceSettings

log = logging.getLogger(__name__)

What = Literal["local_model", "speech_models"]
State = Literal["idle", "running", "done", "failed"]
WHATS: tuple[What, ...] = get_args(What)
ESTIMATE_BYTES: dict[What, int] = {"local_model": 2_100_000_000, "speech_models": 2_000_000_000}
LOCAL_NEEDS = "*.safetensors"


@dataclass(slots=True)
class Job:
    state: State = "idle"
    total: int | None = None
    message: str | None = None


def repo_bytes(repo: str, cache: Path | None = None) -> int:
    """Bytes downloaded so far for `repo`, finished or not."""
    blobs = (cache or hf_cache.hub_cache()) / f"models--{repo.replace('/', '--')}" / "blobs"
    if not blobs.is_dir():
        return 0
    return sum(f.stat().st_size for f in blobs.iterdir() if f.is_file())


class Downloads:
    def __init__(self, config: Callable[[], Config], outside: Callable[[], Outside]) -> None:
        self._config = config
        """The config as saved, so a new local model can be downloaded before a restart."""
        self._outside = outside
        self._jobs: dict[What, Job] = {w: Job() for w in WHATS}
        self._tasks: dict[What, asyncio.Task[None]] = {}
        """Held so a running download's task is not garbage-collected."""

    def repos(self, what: What) -> list[str]:
        config = self._config()
        if what == "local_model":
            return [config.brain.local_model]
        return list(VoiceSettings.from_config(config).model_repos())

    def downloaded(self, what: What) -> bool:
        outside = self._outside()
        needs = LOCAL_NEEDS if what == "local_model" else "*"
        return all(outside.cached_size(repo, needs) is not None for repo in self.repos(what))

    def status(self) -> dict[str, Any]:
        """Every download's state. Reads the disk; run it off the loop."""
        return {what: self._one(what) for what in WHATS}

    def _one(self, what: What) -> dict[str, Any]:
        job = self._jobs[what]
        state = job.state
        if state == "idle" and self.downloaded(what):
            state = "done"
        done = sum(repo_bytes(repo) for repo in self.repos(what))
        total = job.total if job.total is not None else ESTIMATE_BYTES[what]
        return {
            "state": state,
            "done_bytes": done,
            "total_bytes": max(total, done) if state == "done" else total,
            "message": job.message,
        }

    async def start(self, what: What) -> dict[str, Any]:
        """Start a download unless it is running or done; answers every download's state."""
        job = self._jobs[what]
        if job.state == "running" or job.state == "done":
            return await asyncio.to_thread(self.status)
        config = await asyncio.to_thread(self._config)
        if what == "local_model" and config.brain.local_backend != "mlx":
            job.state = "failed"
            job.message = (
                f"The local model is served by {config.brain.local_base_url}, "
                "so there is nothing to download."
            )
            return await asyncio.to_thread(self.status)
        job.state, job.message = "running", None
        self._tasks[what] = asyncio.create_task(self._run(what), name=f"download-{what}")
        return await asyncio.to_thread(self.status)

    async def _run(self, what: What) -> None:
        job = self._jobs[what]
        outside = self._outside()
        config = await asyncio.to_thread(self._config)
        repos = await asyncio.to_thread(self.repos, what)
        try:
            job.total = await asyncio.to_thread(outside.download_size, repos)
            if what == "local_model":
                await asyncio.to_thread(outside.download_local, config.brain.local_model)
            else:
                await asyncio.to_thread(outside.download, repos)
        except Exception as exc:
            log.warning("download of %s failed: %s", what, exc)
            job.state = "failed"
            job.message = (
                f"The download stopped ({exc}). Check the network and the free disk space, "
                "then try again."
            )
        else:
            job.state = "done"
