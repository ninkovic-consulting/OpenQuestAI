"""The composition root: builds every part, wires them to the bus, runs the server.

Each part comes from its package's factory. When a factory raises
`NotImplementedError` (the part is not built yet), or when `--fake-brain` is
passed for the brain, the matching fake from `vision.testing.fakes` is used
and a `notice` says why. If voice fails to start, the daemon continues
text-only with a notice. Startup notices are kept by the snapshot, so a
window that connects later still sees them via `/api/state`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

import uvicorn

from vision import brains, gate, house, memory, voice
from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.events import Notice, NoticeLevel
from vision.core.interfaces import Brain, Budget, House, Memory, ToolHost, Voice
from vision.core.server import create_app
from vision.core.session import Session
from vision.core.snapshot import Snapshot
from vision.core.token import ensure_token
from vision.testing.fakes import (
    FakeBrain,
    FakeBudget,
    FakeHouse,
    FakeMemory,
    FakeToolHost,
    FakeVoice,
)

log = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass(slots=True)
class Components:
    brain: Brain
    tools: ToolHost
    memory: Memory
    budget: Budget
    voice: Voice
    house: House


def build_components(
    config: Config, bus: Bus, *, fake_brain: bool = False
) -> tuple[Components, list[Notice]]:
    """Call every factory, falling back to fakes for parts not built yet."""
    notices: list[Notice] = []

    def build(what: str, factory: Callable[[], T], fallback: Callable[[], T]) -> T:
        try:
            return factory()
        except NotImplementedError:
            notices.append(Notice(level="warn", text=f"{what} is not built yet; using a stand-in."))
            return fallback()

    mem = build("Memory", lambda: memory.make_memory(config), FakeMemory)
    budget = build(
        "The budget", lambda: brains.make_budget(config, bus), lambda: FakeBudget.from_config(config)
    )
    tools = build("The tool gate", lambda: gate.make_tool_host(config, bus, mem), FakeToolHost)
    brain: Brain
    if fake_brain:
        notices.append(Notice(level="info", text="Running on the fake brain (--fake-brain)."))
        brain = FakeBrain()
    else:
        brain = build(
            "The brain", lambda: brains.make_brain(config, bus, tools, mem, budget), FakeBrain
        )
    vox = build("Voice", lambda: voice.make_voice(config, bus), FakeVoice)
    home = build("The house", lambda: house.make_house(config, bus), FakeHouse)
    return Components(brain, tools, mem, budget, vox, home), notices


class Daemon:
    """The whole daemon. `serve()` runs it until cancelled or stopped by signal."""

    def __init__(self, config: Config, *, fake_brain: bool = False, port: int | None = None) -> None:
        self.config = config
        self.port = port or config.server.port
        self.bus = Bus()
        self.token = ensure_token(config.paths.token)
        self.components, self._notices = build_components(config, self.bus, fake_brain=fake_brain)
        self.snapshot = Snapshot(self.bus)
        self.session: Session | None = None
        self._session_task: asyncio.Task[None] | None = None
        self.app = create_app(self)

    def notice(self, level: NoticeLevel, text: str) -> None:
        log.log(logging.WARNING if level != "info" else logging.INFO, "notice: %s", text)
        self.bus.publish(Notice(level=level, text=text))

    async def start(self) -> None:
        self.snapshot.start()
        for n in self._notices:
            self.notice(n.level, n.text)
        c = self.components
        await c.memory.start()
        await c.brain.start()
        try:
            await c.voice.start()
        except Exception as exc:
            log.exception("voice failed to start")
            self.notice("warn", f"Voice is off ({type(exc).__name__}: {exc}). Text still works.")
            c.voice = FakeVoice()
        self.session = Session(self.bus, c.brain, c.voice.speaker, c.memory)
        self._session_task = asyncio.create_task(self.session.run())

    async def stop(self) -> None:
        if self._session_task is not None:
            self._session_task.cancel()
            await asyncio.gather(self._session_task, return_exceptions=True)
        c = self.components
        for step in (c.voice.stop, c.brain.close, c.memory.close, self.snapshot.stop):
            try:
                await step()
            except Exception:
                log.exception("error during shutdown")

    async def serve(self) -> None:
        server = uvicorn.Server(
            uvicorn.Config(
                self.app,
                host=self.config.server.host,
                port=self.port,
                log_level="info",
                ws_ping_interval=20,
            )
        )
        await server.serve()
