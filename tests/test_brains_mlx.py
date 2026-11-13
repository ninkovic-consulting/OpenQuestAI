"""The MLX backend, through the host's local brain, with a stubbed runtime (no model is ever
loaded); the shared engine's turnstile; and one opt-in run of the real model."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest

from vision.brains import make_brain, make_engine
from vision.brains.engine import LocalEngine
from vision.brains.local import LocalBrain
from vision.brains.local_chat import Request, Turnstile
from vision.brains.local_rules import ESSENTIAL, NO_TOOLS, OFFLINE_NO_TOOLS, rules
from vision.brains.mlx_local import MlxBackend, Piece
from vision.brains.router import Router
from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.events import Notice
from vision.core.interfaces import BrainError, BrainEvent, TextDelta, ToolSpec, TurnDone
from vision.testing.fakes import FakeBudget, FakeMemory, FakeToolHost

Message = dict[str, Any]
START, END = "<tool_call>", "</tool_call>"
THINK, UNTHINK = "<think>", "</think>"


class StubSplitter:
    """Normal text, `<think>` sections and `<tool_call>` sections, markers dropped. Markers
    always arrive whole in these tests."""

    def __init__(self) -> None:
        self.state = "normal"

    def feed(self, text: str) -> list[tuple[str, str]]:
        marks = {START: "tool", END: "normal", THINK: "reasoning", UNTHINK: "normal"}
        if text in marks:
            self.state = marks[text]
            return [(self.state, "")]
        return [(self.state, text)]

    def end(self, finish: str | None) -> list[tuple[str, str]]:
        return [(self.state, "")]


GENERATED = 0xE000
"""Generated tokens are private-use characters, so they never equal a re-rendered reply."""


class StubKV:
    """The tokens a model has read, in order: what it "sees" when it generates."""

    def __init__(self, trimmable: bool = True) -> None:
        self.tokens: list[int] = []
        self._trimmable = trimmable

    def trimmable(self) -> bool:
        return self._trimmable

    def trim(self, n: int) -> None:
        del self.tokens[len(self.tokens) - n :]

    def nbytes(self) -> int:
        return 10 * len(self.tokens)

    def size(self) -> int | None:
        return len(self.tokens)


class StubModel:
    """Characters are tokens; the chat prompt is the messages joined. It records exactly which
    tokens each generation read and the whole context it generated from."""

    def __init__(
        self,
        replies: list[list[str]],
        *,
        delay: float = 0.0,
        context: int = 100_000,
        tools: bool = True,
        trimmable: bool = True,
    ) -> None:
        self.replies = replies
        self.delay = delay
        self.context_tokens = context
        self.tools = tools
        self.trimmable = trimmable
        self.weights_bytes = 2_000_000
        self.prompts: list[str] = []
        """The whole context each generation saw, as text."""
        self.read: list[str] = []
        """What each generation read itself (the rest came from the kept prompts)."""
        self.built: list[str] = []
        """The prompt the backend built for each generation."""
        self.progress: list[tuple[int, int]] = []
        self.offered: list[list[str]] = []
        self.thinking: list[bool] = []
        self.generated = 0
        self._last = ""

    def encode(self, text: str) -> list[int]:
        return [ord(c) for c in text]

    def decode(self, tokens: list[int]) -> str:
        return "".join(chr(t) for t in tokens)

    def chat_prompt(self, messages: list[Message], tools: list[dict[str, Any]] | None, thinking: bool) -> list[int]:
        self.offered.append([t["function"]["name"] for t in tools or []])
        self.thinking.append(thinking)
        names = ",".join(t["function"]["name"] for t in tools or [])
        parts = [f"{m['role']}:{m['content']}" for m in messages]
        if names:  # after the system message, as chat templates put them
            parts.insert(1, f"tools:{names}")
        self._last = "|".join(parts)
        return self.encode(self._last)

    def new_kv(self) -> StubKV:
        return StubKV(self.trimmable)

    def stream(self, prompt: list[int], max_tokens: int, kv: Any, progress: Any) -> Iterator[Piece]:
        progress(0, len(prompt))
        self.read.append(self.decode(prompt))
        self.built.append(self._last)
        kv.tokens.extend(prompt)
        self.prompts.append(self.decode(kv.tokens))
        progress(len(prompt), len(prompt))
        self.progress.append((len(prompt), len(prompt)))
        pieces = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        for i, text in enumerate(pieces):
            time.sleep(self.delay)
            self.generated += 1
            token = GENERATED + (ord(text[0]) if text else 0)
            kv.tokens.append(token)
            last = i == len(pieces) - 1
            yield Piece(text, token, i + 1, "stop" if last else None)

    def splitter(self) -> StubSplitter:
        return StubSplitter()

    def parse_calls(self, text: str, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [json.loads(text)]


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
        self.loading = threading.Event()
        self.hold: threading.Event | None = None
        """Set to make `load` wait until it is set."""
        self.fail: Exception | None = None
        self.releases = 0
        self.downloads = 0
        self.tokenizer_reads = 0
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
        self.loading.set()
        if self.hold is not None:
            self.hold.wait(5)
        if self.fail is not None:
            raise self.fail
        return self.model

    def can_call_tools(self, path: Path) -> bool:
        self.tokenizer_reads += 1
        return self.model.tools

    def release(self) -> None:
        self.releases += 1


def engine_on(config: Config, runtime: StubRuntime, bus: Bus | None = None) -> LocalEngine:
    return LocalEngine(
        config, bus or Bus(), factory=lambda cfg, b, backend, repo: MlxBackend(cfg, b, repo, runtime=runtime)
    )


def brain_on(
    config: Config, runtime: StubRuntime, *, core: str = "PERSONA", tools: FakeToolHost | None = None, bus: Bus | None = None
) -> LocalBrain:
    return LocalBrain(config, FakeMemory(core), engine_on(config, runtime, bus), tools)


@pytest.fixture
async def rig(config: Config) -> AsyncIterator[tuple[LocalBrain, StubRuntime]]:
    runtime = StubRuntime(StubModel([["Hel", "lo", "."]]))
    brain = brain_on(config, runtime)
    await brain.start()
    yield brain, runtime
    await brain.close()


async def collect(brain: LocalBrain, text: str = "hi", heavy: bool = False) -> list[BrainEvent]:
    return [e async for e in brain.send(text, heavy=heavy)]


def said(events: list[BrainEvent]) -> str:
    return "".join(e.text for e in events if isinstance(e, TextDelta))


def host(*names: str) -> FakeToolHost:
    async def run(args: dict[str, Any]) -> str:
        return f"ran with {json.dumps(args, sort_keys=True)}"

    schema = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}
    return FakeToolHost({n: (ToolSpec(n, f"The {n} tool.", schema), run) for n in names})


def test_factory_builds_a_router_over_the_shared_engine(config: Config) -> None:
    bus = Bus()
    engine = make_engine(config, bus)
    router = make_brain(config, bus, FakeToolHost(), FakeMemory(), FakeBudget(), engine)
    assert isinstance(router, Router) and isinstance(router._local, LocalBrain)
    assert router._local.engine is engine


async def test_streams_text_and_counts(rig: tuple[LocalBrain, StubRuntime]) -> None:
    brain, runtime = rig
    events = await collect(brain, "hi")
    prompt_tokens = len(runtime.model.prompts[0])
    assert events == [
        TextDelta("Hel"),
        TextDelta("lo"),
        TextDelta("."),
        TurnDone(brain.model, prompt_tokens, 3, "end_turn"),
    ]
    system = f"system:PERSONA\n\n{NO_TOOLS}"
    assert runtime.model.prompts[0] == f"{system}|user:hi"
    await collect(brain, "again")
    assert runtime.model.prompts[1] == f"{system}|user:hi|assistant:Hello.|user:again"
    assert all(name.startswith("mlx") for name in runtime.threads)


async def test_offline_says_why_it_has_no_tools(config: Config) -> None:
    config.brain.offline = True
    runtime = StubRuntime(StubModel([["ok"]], tools=False))
    brain = brain_on(config, runtime, tools=host("remember"))
    await brain.start()
    try:
        await collect(brain)
    finally:
        await brain.close()
    assert OFFLINE_NO_TOOLS in runtime.model.prompts[0] and runtime.model.offered == [[], []]


async def test_loads_lazily_once(rig: tuple[LocalBrain, StubRuntime]) -> None:
    brain, runtime = rig
    assert runtime.loads == 0
    await collect(brain)
    await collect(brain)
    assert runtime.loads == 1


async def test_unloads_after_idle_and_reloads(config: Config) -> None:
    config.brain.local_idle_unload_s = 0.05
    runtime = StubRuntime(StubModel([["Hi."]]))
    brain = brain_on(config, runtime)
    await brain.start()
    try:
        await collect(brain)
        async with asyncio.timeout(2):
            while runtime.releases == 0:
                await asyncio.sleep(0.01)
        await collect(brain)
        assert runtime.loads == 2
    finally:
        await brain.close()


async def test_interrupt_stops_generation_promptly(config: Config) -> None:
    model = StubModel([[f"w{i} " for i in range(200)]], delay=0.01)
    brain = brain_on(config, StubRuntime(model))
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
    model = StubModel([["ok"]], context=1024, tools=False)
    brain = brain_on(config, StubRuntime(model), core="P" * 5000)
    await brain.start()
    try:
        await collect(brain, "hi")
    finally:
        await brain.close()
    prompt = model.prompts[0]
    assert prompt.startswith("system:PPP") and prompt.endswith(f"{NO_TOOLS}|user:hi")
    assert len(prompt) <= 1024 - 100


async def test_a_missing_model_is_never_fetched(config: Config) -> None:
    runtime = StubRuntime(StubModel([["Hi."]]), on_disk=False)
    bus = Bus()
    sub = bus.subscribe({Notice.TYPE})
    brain = brain_on(config, runtime, bus=bus)
    await brain.start()
    try:
        async with asyncio.timeout(2):
            first = await collect(brain)
            again = await collect(brain)
    finally:
        await brain.close()
    for events in (first, again):
        [error] = events
        assert isinstance(error, BrainError) and error.kind == "unavailable"
        assert error.message.startswith("No local model is downloaded on this Mac")
        assert "Settings, under Models" in error.message
    assert runtime.downloads == 0 and runtime.loads == 0
    notice = sub._queue.get_nowait()
    assert notice.level == "warn" and notice.text == first[0].message
    assert sub._queue.empty()  # said once, not on every turn


async def test_missing_extra_fails_clearly(config: Config) -> None:
    class NoMlx(StubRuntime):
        def cached(self, repo: str) -> Path | None:
            raise ImportError("mlx_lm")

    brain = brain_on(config, NoMlx(StubModel([["x"]])))
    await brain.start()
    try:
        [error] = await collect(brain)
    finally:
        await brain.close()
    assert isinstance(error, BrainError) and "--extra local" in error.message


async def test_tools_follow_the_template_and_go_through_the_host(config: Config) -> None:
    call = json.dumps({"name": "remember", "arguments": {"text": "milk"}})
    model = StubModel(
        [
            [THINK, "the user wants a note", UNTHINK, "On it.", START, call, END],
            ["Saved", " it."],
        ]
    )
    tools = host("remember", "hand_off")
    brain = brain_on(config, StubRuntime(model), tools=tools)
    await brain.start()
    try:
        events = await collect(brain, "Remember milk", heavy=True)
    finally:
        await brain.close()
    assert tools.calls == [("remember", {"text": "milk"})]
    assert said(events) == "On it. Saved it."  # the thinking is never said
    assert model.offered[-1] == ["remember", "hand_off"] and model.thinking[-1] is True
    second = model.prompts[1]
    assert rules(tools=True, offline=False) in second
    assert 'tool:ran with {"text": "milk"}' in second
    assert isinstance(events[-1], TurnDone) and events[-1].stop_reason == "end_turn"


async def test_a_small_model_gets_the_short_list(config: Config) -> None:
    model = StubModel([["ok"]])
    names = ["remember", "create_automation", "room_details", "hand_off"]
    brain = brain_on(config, StubRuntime(model), tools=host(*names))  # the default 4B model
    await brain.start()
    try:
        await collect(brain)
    finally:
        await brain.close()
    assert model.offered[-1] == [n for n in names if n in ESSENTIAL] == ["remember", "hand_off"]


async def test_an_unreadable_call_is_answered_not_run(config: Config) -> None:
    model = StubModel([[START, "{not json", END], ["Sorry, I will just say it."]])
    tools = host("remember")
    brain = brain_on(config, StubRuntime(model), tools=tools)
    await brain.start()
    try:
        events = await collect(brain)
    finally:
        await brain.close()
    assert tools.calls == [] and said(events) == "Sorry, I will just say it."
    assert "Tool error: these calls were not run" in model.prompts[1] and "could not be read" in model.prompts[1]


async def test_the_turnstile_serves_the_host_first() -> None:
    gate = Turnstile()
    order: list[str] = []
    release = asyncio.Event()

    async def hold() -> None:
        async with gate.turn("job"):
            order.append("job-1")
            await release.wait()

    async def take(who: Any, name: str) -> None:
        async with gate.turn(who):
            order.append(name)

    first = asyncio.create_task(hold())
    await asyncio.sleep(0)
    waiting = [asyncio.create_task(take("job", "job-2")), asyncio.create_task(take("host", "host"))]
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(first, *waiting)
    assert order == ["job-1", "host", "job-2"] and not gate.busy


async def test_the_engine_follows_a_new_model_and_frees_the_old(config: Config) -> None:
    runtimes: dict[str, StubRuntime] = {}

    def make(cfg: Config, bus: Bus, backend: str, repo: str) -> MlxBackend:
        runtimes[repo] = StubRuntime(StubModel([[repo]]))
        return MlxBackend(cfg, bus, repo, runtime=runtimes[repo])

    engine = LocalEngine(config, Bus(), factory=make)
    request = Request(core="", rules="r", messages=[{"role": "user", "content": "hi"}], tools=[], max_tokens=10)
    old = config.brain.local_model
    assert (await engine.generate(request, "host")).text == old
    config.brain.local_model = "mlx-community/Qwen3-8B-4bit"
    assert (await engine.generate(request, "job")).text == "mlx-community/Qwen3-8B-4bit"
    assert runtimes[old].releases == 1
    await engine.close()


@pytest.mark.skipif(os.environ.get("VISION_LOCAL_MODEL") != "1", reason="set VISION_LOCAL_MODEL=1")
async def test_real_model_answers(config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    """Loads the configured model from the real Hugging Face cache and answers a short prompt."""
    monkeypatch.delenv("HF_HUB_CACHE")
    brain = LocalBrain(config, FakeMemory("You are a helpful assistant. Answer briefly."), make_engine(config, Bus()), None)
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
    assert said(events).strip()
    print(f"\nreply={said(events)!r} first_text_s={first:.2f} total_s={total:.2f} "
          f"prompt_tokens={done.input_tokens} output_tokens={done.output_tokens}")
