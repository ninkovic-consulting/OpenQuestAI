"""The in-process MLX brain with a stubbed runtime, plus one opt-in run of the real model."""

from __future__ import annotations

import asyncio
import os
import threading
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

from vision.brains import make_brain
from vision.brains.mlx_local import MlxBrain, Piece
from vision.brains.router import Router
from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.events import Notice
from vision.core.interfaces import BrainError, BrainEvent, TextDelta, TurnDone
from vision.testing.fakes import FakeBudget, FakeMemory, FakeToolHost

Message = dict[str, str]


class StubModel:
    """Characters are tokens; the chat prompt is the messages joined."""

    def __init__(self, pieces: list[str], *, delay: float = 0.0, context: int = 100_000) -> None:
        self.pieces = pieces
        self.delay = delay
        self.context_tokens = context
        self.prompts: list[str] = []
        self.generated = 0

    def encode(self, text: str) -> list[int]:
        return [ord(c) for c in text]

    def decode(self, tokens: list[int]) -> str:
        return "".join(chr(t) for t in tokens)

    def chat_prompt(self, messages: list[Message]) -> list[int]:
        return self.encode("|".join(f"{m['role']}:{m['content']}" for m in messages))

    def stream(self, prompt: list[int], max_tokens: int) -> Iterator[Piece]:
        self.prompts.append(self.decode(prompt))
        for i, text in enumerate(self.pieces):
            time.sleep(self.delay)
            self.generated += 1
            last = i == len(self.pieces) - 1
            yield Piece(text, len(prompt), i + 1, "stop" if last else None)


class StubRuntime:
    def __init__(
        self,
        model: StubModel,
        *,
        on_disk: bool = True,
        online: bool = True,
        size: int = 2_300_000_000,
    ) -> None:
        self.model = model
        self.on_disk = on_disk
        self.online = online
        self.size = size
        self.loads = 0
        self.releases = 0
        self.downloads = 0
        self.threads: set[str] = set()

    def _here(self) -> None:
        self.threads.add(threading.current_thread().name)

    def cached(self, repo: str) -> Path | None:
        self._here()
        return Path("/models/stub") if self.on_disk else None

    def download_size(self, repo: str) -> int:
        if not self.online:
            raise ConnectionError("offline")
        return self.size

    def download(self, repo: str) -> Path:
        self.downloads += 1
        self.on_disk = True
        return Path("/models/stub")

    def load(self, path: Path) -> StubModel:
        self._here()
        self.loads += 1
        return self.model

    def release(self) -> None:
        self.releases += 1


@pytest.fixture
async def rig(config: Config) -> AsyncIterator[tuple[MlxBrain, StubRuntime, Bus]]:
    runtime = StubRuntime(StubModel(["Hel", "lo", "."]))
    bus = Bus()
    brain = MlxBrain(config, bus, FakeMemory("PERSONA"), runtime=runtime)
    await brain.start()
    yield brain, runtime, bus
    await brain.close()


async def collect(brain: MlxBrain, text: str = "hi") -> list[BrainEvent]:
    return [e async for e in brain.send(text)]


def test_factory_picks_the_backend(config: Config) -> None:
    def local(cfg: Config) -> object:
        router = make_brain(cfg, Bus(), FakeToolHost(), FakeMemory(), FakeBudget())
        assert isinstance(router, Router)
        return router._local

    assert type(local(config)).__name__ == "MlxBrain"
    config.brain.local_backend = "openai"
    assert type(local(config)).__name__ == "LocalBrain"


async def test_streams_text_and_counts(rig: tuple[MlxBrain, StubRuntime, Bus]) -> None:
    brain, runtime, _ = rig
    events = await collect(brain, "hi")
    model = brain.model
    prompt_tokens = len(runtime.model.prompts[0])
    assert events == [
        TextDelta("Hel"),
        TextDelta("lo"),
        TextDelta("."),
        TurnDone(model, prompt_tokens, 3, "end_turn"),
    ]
    assert runtime.model.prompts[0] == "system:PERSONA|user:hi"
    await collect(brain, "again")
    assert runtime.model.prompts[1] == "system:PERSONA|user:hi|assistant:Hello.|user:again"
    assert all(name.startswith("mlx") for name in runtime.threads)


async def test_loads_lazily_once(rig: tuple[MlxBrain, StubRuntime, Bus]) -> None:
    brain, runtime, _ = rig
    assert runtime.loads == 0 and not brain.loaded
    await collect(brain)
    await collect(brain)
    assert runtime.loads == 1 and brain.loaded


async def test_unloads_after_idle_and_reloads(config: Config) -> None:
    config.brain.local_idle_unload_s = 0.05
    runtime = StubRuntime(StubModel(["Hi."]))
    brain = MlxBrain(config, Bus(), FakeMemory(), runtime=runtime)
    await brain.start()
    try:
        await collect(brain)
        assert brain.loaded
        async with asyncio.timeout(2):
            while brain.loaded:
                await asyncio.sleep(0.01)
        assert runtime.releases == 1
        await collect(brain)
        assert runtime.loads == 2
    finally:
        await brain.close()


async def test_interrupt_stops_generation_promptly(config: Config) -> None:
    model = StubModel([f"w{i} " for i in range(200)], delay=0.01)
    brain = MlxBrain(config, Bus(), FakeMemory(), runtime=StubRuntime(model))
    await brain.start()
    try:
        events: list[BrainEvent] = []
        started = time.monotonic()
        async for event in brain.send("long"):
            events.append(event)
            if len(events) == 2:
                await brain.interrupt()
        elapsed = time.monotonic() - started
        assert isinstance(events[-1], TurnDone) and events[-1].stop_reason == "interrupted"
        assert elapsed < 1.0
        await asyncio.sleep(0.1)
        assert model.generated < 20  # the worker thread stopped too
    finally:
        await brain.close()


async def test_system_prompt_is_trimmed_to_fit(config: Config) -> None:
    config.brain.max_output_tokens = 100
    model = StubModel(["ok"], context=1024)
    brain = MlxBrain(config, Bus(), FakeMemory("P" * 5000), runtime=StubRuntime(model))
    await brain.start()
    try:
        await collect(brain, "hi")
    finally:
        await brain.close()
    prompt = model.prompts[0]
    assert prompt.startswith("system:PPP") and prompt.endswith("|user:hi")
    assert len(prompt) <= 1024 - 100


async def test_downloads_with_a_notice_when_missing(config: Config) -> None:
    runtime = StubRuntime(StubModel(["Hi."]), on_disk=False)
    bus = Bus()
    sub = bus.subscribe({Notice.TYPE})
    brain = MlxBrain(config, bus, FakeMemory(), runtime=runtime)
    await brain.start()
    try:
        events = await collect(brain)
    finally:
        await brain.close()
    assert events[0] == TextDelta("Hi.")
    notice = sub._queue.get_nowait()
    assert "Downloading the local model" in notice.text and "2.3 GB" in notice.text
    assert runtime.downloads == 1


async def test_missing_and_offline_fails_clearly(config: Config) -> None:
    runtime = StubRuntime(StubModel(["Hi."]), on_disk=False, online=False)
    brain = MlxBrain(config, Bus(), FakeMemory(), runtime=runtime)
    await brain.start()
    try:
        async with asyncio.timeout(2):
            events = await collect(brain)
    finally:
        await brain.close()
    [error] = events
    assert isinstance(error, BrainError) and error.kind == "unavailable"
    assert "Download it in Settings" in error.message and runtime.loads == 0


async def test_missing_extra_fails_clearly(config: Config) -> None:
    class NoMlx(StubRuntime):
        def cached(self, repo: str) -> Path | None:
            raise ImportError("mlx_lm")

    brain = MlxBrain(config, Bus(), FakeMemory(), runtime=NoMlx(StubModel(["x"])))
    await brain.start()
    try:
        [error] = await collect(brain)
    finally:
        await brain.close()
    assert isinstance(error, BrainError) and "--extra local" in error.message


@pytest.mark.skipif(os.environ.get("VISION_LOCAL_MODEL") != "1", reason="set VISION_LOCAL_MODEL=1")
async def test_real_model_answers(config: Config) -> None:
    """Loads (and if needed downloads) the configured model and answers a short prompt."""
    brain = MlxBrain(config, Bus(), FakeMemory("You are a helpful assistant. Answer briefly."))
    await brain.start()
    try:
        started = time.monotonic()
        first: float | None = None
        events: list[BrainEvent] = []
        async for event in brain.send("Say hello in five words."):
            if first is None and isinstance(event, TextDelta):
                first = time.monotonic() - started
            events.append(event)
        total = time.monotonic() - started
    finally:
        await brain.close()
    done = events[-1]
    assert isinstance(done, TurnDone), events
    text = "".join(e.text for e in events if isinstance(e, TextDelta))
    assert text.strip()
    print(f"\nreply={text!r} first_text_s={first:.2f} total_s={total:.2f} "
          f"prompt_tokens={done.input_tokens} output_tokens={done.output_tokens}")
