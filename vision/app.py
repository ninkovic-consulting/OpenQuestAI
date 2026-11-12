"""The composition root: builds every part, wires them to the bus, runs the server.

Each part comes from its package's factory. With `--fake-brain` the brain is
the scripted fake from `vision.testing.fakes`, with a `notice` saying so.
Voice can be swapped for another factory (`vision run --voice-in/--voice-out`
runs the real pipeline on WAV files), and tests may hand the daemon all its
parts. If voice fails to start, the daemon continues text-only with a notice.
Startup notices are kept by the snapshot, so a window that connects later
still sees them via `/api/state`.

Start-up order: `$VISION_HOME` is made private (0700); the house's agent
personas are copied into the vault (never overwriting), so memory reads the
house's host persona; then memory, the house, the brain and voice start, the
budget is published, and the Hall's light starts following the conversation.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import uvicorn

from vision import brains, gate, house, memory, voice
from vision.core.bus import Bus, Subscription
from vision.core.config import Config
from vision.core.events import BudgetUpdate, Notice, NoticeLevel, RoomLight, RoomState, StateChanged
from vision.core.interfaces import Brain, Budget, House, Memory, ToolHost, Voice
from vision.core.server import create_app
from vision.core.session import Session
from vision.core.snapshot import Snapshot
from vision.core.token import ensure_token
from vision.testing.fakes import FakeBrain, FakeVoice

log = logging.getLogger(__name__)

HALL = "hall"
"""The host's room; its light follows the conversation."""

ComponentsFactory = Callable[[Bus], "Components"]
VoiceFactory = Callable[[Config, Bus], Voice]


@dataclass(slots=True)
class Components:
    brain: Brain
    tools: ToolHost
    memory: Memory
    budget: Budget
    voice: Voice
    house: House


def build_components(
    config: Config, bus: Bus, *, fake_brain: bool = False, voice_factory: VoiceFactory | None = None
) -> tuple[Components, list[Notice]]:
    """Call every package's factory. `voice_factory` replaces `vision.voice.make_voice`."""
    notices: list[Notice] = []
    mem = memory.make_memory(config)
    budget = brains.make_budget(config, bus)
    tools = gate.make_tool_host(config, bus, mem)
    brain: Brain
    if fake_brain:
        notices.append(Notice(level="info", text="Running on the fake brain (--fake-brain)."))
        brain = FakeBrain()
    else:
        brain = brains.make_brain(config, bus, tools, mem, budget)
    vox = (voice_factory or voice.make_voice)(config, bus)
    home = house.make_house(config, bus)
    return Components(brain, tools, mem, budget, vox, home), notices


def ensure_home(home: Path) -> None:
    """Create `$VISION_HOME` if needed and keep it private to the user (0700)."""
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(home, 0o700)


def hall_light(state: str) -> RoomLight:
    return "active" if state in ("thinking", "speaking") else "idle"


class Daemon:
    """The whole daemon. `serve()` runs it until cancelled or stopped by signal.

    `components` builds every part on the daemon's bus instead of the
    packages' factories (tests use it to run on fakes); `voice` replaces only
    the voice factory.
    """

    def __init__(
        self,
        config: Config,
        *,
        fake_brain: bool = False,
        port: int | None = None,
        components: ComponentsFactory | None = None,
        voice: VoiceFactory | None = None,
    ) -> None:
        self.config = config
        self.port = port or config.server.port
        ensure_home(config.paths.home)
        self.bus = Bus()
        self.token = ensure_token(config.paths.token)
        if components is None:
            built = build_components(
                config, self.bus, fake_brain=fake_brain, voice_factory=voice
            )
            self.components, self._notices = built
        else:
            self.components, self._notices = components(self.bus), []
        self._voice_factory = voice
        self._voice_lock = asyncio.Lock()
        self.voice_running = False
        """True while the microphone loop runs."""
        self.voice_error: str | None = None
        """Why voice last failed to start, or None."""
        self.snapshot = Snapshot(self.bus)
        self.session: Session | None = None
        self._session_task: asyncio.Task[None] | None = None
        self._lights_task: asyncio.Task[None] | None = None
        self.app = create_app(self)

    def notice(self, level: NoticeLevel, text: str) -> None:
        log.log(logging.WARNING if level != "info" else logging.INFO, "notice: %s", text)
        self.bus.publish(Notice(level=level, text=text))

    async def start(self) -> None:
        self.snapshot.start()
        for n in self._notices:
            self.notice(n.level, n.text)
        c = self.components
        await asyncio.to_thread(house.seed_personas, self.config)
        await c.memory.start()
        await c.house.start()
        await c.brain.start()
        self.bus.publish(BudgetUpdate(**dataclasses.asdict(c.budget.status())))
        try:
            await c.voice.start()
        except Exception as exc:
            log.exception("voice failed to start")
            self.notice("warn", f"Voice is off ({type(exc).__name__}: {exc}). Text still works.")
            c.voice = FakeVoice()
            self.voice_error = str(exc)
        else:
            self.voice_running = True
        states = self.bus.subscribe({StateChanged.TYPE})
        self._lights_task = asyncio.create_task(self._light_the_hall(states))
        self.session = Session(self.bus, c.brain, c.voice.speaker, c.memory, c.tools)
        self._session_task = asyncio.create_task(self.session.run())

    async def set_voice(self, enabled: bool) -> None:
        """Turn the microphone loop on or off now, without a restart.

        Stops the current voice, then (when `enabled`) builds a new one from the
        current config and starts it. On failure the daemon keeps a silent voice
        and `voice_error` says why. The session speaks through the new speaker.
        """
        async with self._voice_lock:
            c = self.components
            try:
                await c.voice.stop()
            except Exception:
                log.exception("stopping voice failed")
            self.voice_running, self.voice_error = False, None
            new: Voice = FakeVoice()
            if enabled:
                candidate = (self._voice_factory or voice.make_voice)(self.config, self.bus)
                try:
                    await candidate.start()
                except Exception as exc:
                    log.warning("voice failed to start: %s", exc)
                    self.voice_error = str(exc) or type(exc).__name__
                    with contextlib.suppress(Exception):
                        await candidate.stop()
                else:
                    new, self.voice_running = candidate, True
            c.voice = new
            if self.session is not None:
                self.session.speaker = new.speaker

    async def _light_the_hall(self, states: Subscription) -> None:
        """Keep the Hall `active` while thinking or speaking and `idle` otherwise."""
        lit: RoomLight = "idle"
        async with states as sub:
            async for event in sub:
                assert isinstance(event, StateChanged)
                light = hall_light(event.state)
                if light != lit:
                    lit = light
                    self.components.house.set_room_state(HALL, light)
                    self.bus.publish(RoomState(room=HALL, state=light))

    async def stop(self) -> None:
        for task in (self._session_task, self._lights_task):
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        c = self.components
        steps = (c.voice.stop, c.brain.close, c.house.close, c.memory.close, self.snapshot.stop)
        for step in steps:
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
