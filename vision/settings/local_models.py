"""The local models in Settings: the catalog against this Mac, downloads, deleting, the server.

- `listing()` is `GET /api/local-models`: the catalog (`vision.brains.catalog`)
  with this Mac's memory, each entry's fit, the recommendation, the chosen
  model, offline mode, and for each entry what is on disk and its download.
- `download(repo)` fetches any Hugging Face repo in the background (only
  weights, configs, tokenizer and template); progress is measured on disk.
  A download cannot be cancelled: the Hub client has no way to stop one.
- `delete(repo)` removes a model from the Hugging Face cache, but never the
  one offline mode is using.
- `test_server(body)` asks an OpenAI-compatible server for its models.
- `check(fresh, saved)` is the part of a settings change that needs the disk or
  a server: an MLX model must be a Hugging Face repo, and offline mode can only
  be on when its model is downloaded (MLX) or its server answers and has the
  model (OpenAI-compatible).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from vision.brains import catalog
from vision.brains.local_server import server_key
from vision.brains.mlx_local import NEEDS
from vision.core.config import Config
from vision.settings.downloads import repo_bytes
from vision.settings.outside import Outside
from vision.settings.values import HF_REPO, SERVER_URL

if TYPE_CHECKING:
    from vision.app import Daemon

log = logging.getLogger(__name__)

State = Literal["idle", "running", "done", "failed"]


class NotAllowed(ValueError):
    """A request that cannot be done; the message is for people."""


@dataclass(slots=True)
class _Download:
    state: State = "idle"
    total: int | None = None
    message: str | None = None


class LocalModels:
    def __init__(
        self, daemon: Daemon, saved: Callable[[], Config], outside: Callable[[], Outside]
    ) -> None:
        self._daemon = daemon
        self._saved = saved
        self._outside = outside
        self._downloads: dict[str, _Download] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        """Held so a running download's task is not garbage-collected."""

    # ------------------------------------------------------------ reading

    def listing(self) -> dict[str, Any]:
        """The `GET /api/local-models` answer. Reads the disk; run it off the loop."""
        outside = self._outside()
        saved = self._saved()
        memory = outside.memory_bytes()
        answer = catalog.listing(memory)
        brain = saved.brain
        for row in answer["models"]:
            row.update(self._disk(row["id"], row["size_bytes"]))
        chosen = None
        if brain.local_backend == "mlx" and catalog.load_catalog().get(brain.local_model) is None:
            chosen = {"id": brain.local_model, **self._disk(brain.local_model, None)}
        return {
            **answer,
            "chosen": {
                "backend": brain.local_backend,
                "model": brain.local_model,
                "server": brain.local_base_url,
                "tools": self._daemon.local.known_tools(),
            },
            "custom": chosen,
            "offline": brain.offline,
        }

    def _disk(self, repo: str, size: int | None) -> dict[str, Any]:
        on_disk = self._outside().cached_size(repo, NEEDS)
        job = self._downloads.get(repo, _Download())
        state: State = "done" if job.state == "idle" and on_disk is not None else job.state
        done = repo_bytes(repo)
        total = job.total if job.total is not None else size
        return {
            "on_disk_bytes": on_disk,
            "download": {
                "state": state,
                "done_bytes": done,
                "total_bytes": max(total or 0, done) if state == "done" else total,
                "message": job.message,
            },
        }

    # ------------------------------------------------------------ changing

    async def download(self, repo: Any) -> dict[str, Any]:
        """Start fetching `repo` unless it is running or on disk; answers the listing."""
        name = _repo(repo)
        job = self._downloads.setdefault(name, _Download())
        if job.state != "running" and await asyncio.to_thread(self._outside().cached_size, name, NEEDS) is None:
            job.state, job.message = "running", None
            self._tasks[name] = asyncio.create_task(self._run(name, job), name=f"download-{name}")
        return await asyncio.to_thread(self.listing)

    async def _run(self, repo: str, job: _Download) -> None:
        outside = self._outside()
        try:
            job.total = await asyncio.to_thread(outside.download_size, [repo])
            await asyncio.to_thread(outside.download_local, repo)
        except Exception as exc:
            log.warning("download of %s failed: %s", repo, exc)
            job.state = "failed"
            job.message = (
                f"The download stopped ({exc}). Check the network, the free disk space and the "
                "repo's name, then try again."
            )
        else:
            job.state = "done"
        finally:
            self._tasks.pop(repo, None)

    async def delete(self, repo: Any) -> dict[str, Any]:
        name = _repo(repo)
        brain = self._daemon.config.brain
        if brain.offline and brain.local_backend == "mlx" and brain.local_model == name:
            raise NotAllowed(
                f"{name} is the model offline mode is using. Choose another or turn offline mode off first."
            )
        if self._downloads.get(name, _Download()).state == "running":
            raise NotAllowed(f"{name} is still downloading.")
        freed = await asyncio.to_thread(self._outside().delete_local, name)
        self._downloads.pop(name, None)
        return {"deleted": name, "freed_bytes": freed, **await asyncio.to_thread(self.listing)}

    async def test_server(self, body: dict[str, Any]) -> dict[str, Any]:
        """Ask the server (the one given, else the saved one) for its models."""
        saved = await asyncio.to_thread(self._saved)
        url = body.get("server", saved.brain.local_base_url)
        if not isinstance(url, str) or not SERVER_URL.match(url.strip()):
            raise NotAllowed("The server address is an http:// or https:// address, like http://127.0.0.1:1234/v1.")
        found = await self._outside().probe_server(url.strip().rstrip("/"), server_key(saved))
        return {"ok": found.ok, "models": found.models, "message": found.message}

    async def check(self, fresh: Config, saved: Config) -> list[dict[str, str]]:
        """Problems with the local-model part of a change, as `{field, message}`."""
        brain = fresh.brain
        if brain.local_backend == "mlx" and not HF_REPO.match(brain.local_model):
            return [
                {
                    "field": "models.local",
                    "message": "On this Mac (mlx) the local model is a Hugging Face repo, like "
                    "mlx-community/Qwen3-4B-Instruct-2507-4bit.",
                }
            ]
        before = saved.brain
        moved = (brain.local_backend, brain.local_model, brain.local_base_url) != (
            before.local_backend,
            before.local_model,
            before.local_base_url,
        )
        if not brain.offline or (before.offline and not moved):
            return []
        field = "models.offline" if not before.offline else "models.local"
        if brain.local_backend == "mlx":
            on_disk = await asyncio.to_thread(self._outside().cached_size, brain.local_model, NEEDS)
            if on_disk is None:
                return [
                    {
                        "field": field,
                        "message": f"Offline mode needs the local model on this Mac, and {brain.local_model} "
                        "is not downloaded yet. Download it under Models while online, then turn offline "
                        "mode on.",
                    }
                ]
            return []
        found = await self._outside().probe_server(brain.local_base_url, server_key(fresh))
        if not found.ok:
            return [{"field": field, "message": f"Offline mode needs the local server. {found.message}"}]
        if found.models and brain.local_model not in found.models:
            return [
                {
                    "field": field,
                    "message": f"The server at {brain.local_base_url} has no model called {brain.local_model}. "
                    f"It has: {', '.join(found.models)}.",
                }
            ]
        return []


def _repo(value: Any) -> str:
    text = value.strip() if isinstance(value, str) else ""
    if not HF_REPO.match(text) or ".." in text:
        raise NotAllowed("Name a Hugging Face repo, like mlx-community/Qwen3-8B-4bit.")
    return text
