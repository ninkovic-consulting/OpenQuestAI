"""The local model, shared by the host and the residents: one backend, one generation at a time.

The engine follows `[brain] local_backend`, `local_model` and `local_base_url`
as they are now, so Settings can change them while the daemon runs: the next
generation after a change closes the old backend (freeing an MLX model's
memory) and starts the new one. That happens inside the turnstile, so no
generation is ever cut off by a change.

`interrupt()` stops a generation only when it is the host's (the owner said
stop); a resident's step goes on.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Protocol

from vision.brains import catalog
from vision.brains.local_chat import OnText, Reply, Request, Turnstile, Who
from vision.brains.local_server import ServerBackend
from vision.brains.mlx_local import MlxBackend
from vision.core.bus import Bus
from vision.core.config import Config
from vision.setup import hf_cache

Key = tuple[str, str, str]


class Backend(Protocol):
    model: str

    @property
    def known_tools(self) -> bool | None: ...
    async def start(self) -> None: ...
    def stop(self) -> None: ...
    async def close(self) -> None: ...
    async def ready(self) -> str | None: ...
    async def can_call_tools(self) -> bool: ...
    async def generate(self, request: Request, on_text: OnText | None) -> Reply: ...


Factory = Callable[[Config, Bus, str, str], Backend]


def make_backend(config: Config, bus: Bus, backend: str, repo: str) -> Backend:
    if backend == "mlx":
        return MlxBackend(config, bus, repo)
    return ServerBackend(config, repo)


class LocalEngine:
    def __init__(self, config: Config, bus: Bus, *, factory: Factory = make_backend) -> None:
        self._config = config
        self._bus = bus
        self._factory = factory
        self._turnstile = Turnstile()
        self._backends: dict[Key, Backend] = {}
        self._active: Key | None = None
        self._holder: Who | None = None

    # ------------------------------------------------------------ what it runs

    @property
    def model(self) -> str:
        return self._config.brain.local_model

    @property
    def backend(self) -> str:
        return self._config.brain.local_backend

    @property
    def busy(self) -> bool:
        return self._turnstile.busy

    def known_tools(self) -> bool | None:
        """Whether the chosen model can call tools, when that is already known."""
        found = self._backends.get(self._key())
        return found.known_tools if found is not None else None

    def small(self) -> bool:
        """A small model is offered a short list of tools (`local_rules.ESSENTIAL`)."""
        size = hf_cache.cached_size(self.model) if self.backend == "mlx" else None
        return catalog.is_small(self.model, size)

    def _key(self) -> Key:
        b = self._config.brain
        return (b.local_backend, b.local_model, b.local_base_url.rstrip("/"))

    async def _get(self, key: Key) -> Backend:
        found = self._backends.get(key)
        if found is None:
            found = self._factory(self._config, self._bus, key[0], key[1])
            await found.start()
            self._backends[key] = found
        return found

    # ------------------------------------------------------------ lifetime

    async def close(self) -> None:
        backends, self._backends = list(self._backends.values()), {}
        for backend in backends:
            await backend.close()

    async def interrupt(self) -> None:
        """Stop the host's generation in progress, if one runs."""
        if self._holder == "host" and self._active is not None:
            backend = self._backends.get(self._active)
            if backend is not None:
                backend.stop()

    # ------------------------------------------------------------ asking

    async def ready(self) -> str | None:
        """Why the chosen model cannot answer without the internet now, or None."""
        return await (await self._get(self._key())).ready()

    async def can_call_tools(self) -> bool:
        return await (await self._get(self._key())).can_call_tools()

    async def generate(self, request: Request, who: Who, on_text: OnText | None = None) -> Reply:
        """One generation, in turn: the host's go before the residents'."""
        async with self._turnstile.turn(who):
            key = self._key()
            await self._retire(key)
            backend = await self._get(key)
            self._active, self._holder = key, who
            try:
                return await backend.generate(request, on_text)
            finally:
                self._holder = None

    async def _retire(self, keep: Key) -> None:
        """Close the backends of models no longer chosen (their memory is freed)."""
        for key in [k for k in self._backends if k != keep]:
            backend = self._backends.pop(key)
            await asyncio.shield(backend.close())
