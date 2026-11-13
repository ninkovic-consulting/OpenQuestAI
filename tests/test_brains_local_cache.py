"""The local model kept loaded and its processed prompts kept between generations, on a stub
runtime that records exactly which tokens each generation read and the whole context it
generated from. No model is ever loaded."""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any

import pytest
from test_brains_mlx import END, START, StubKV, StubModel, StubRuntime, brain_on, collect, engine_on, host, said

from vision.brains import mode
from vision.brains.engine import LocalEngine
from vision.brains.local_chat import Request, Status
from vision.brains.mlx_local import READING_SHOWN, MlxBackend, cannot_load
from vision.brains.prompt_cache import MIN_SHARED, PromptCaches
from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.events import BrainMode, Notice
from vision.residents.local_worker import LocalSession, work_local
from vision.testing.fakes import FakeMemory

PERSONA = "You are a calm assistant who keeps answers short. " * 3


def shared(a: str, b: str) -> int:
    n = 0
    while n < min(len(a), len(b)) and a[n] == b[n]:
        n += 1
    return n


def honest(model: StubModel) -> None:
    """Every generation saw exactly the prompt built for it: nothing more, nothing else."""
    assert model.prompts == model.built


# ------------------------------------------------------------ reading only what is new


async def test_a_turn_reads_only_what_is_new(config: Config) -> None:
    model = StubModel([["Hel", "lo."]])
    brain = brain_on(config, StubRuntime(model), core=PERSONA, tools=host("remember"))
    await brain.start()
    try:
        for text in ("hi", "and again", "once more"):
            await collect(brain, text)
    finally:
        await brain.close()
    honest(model)
    assert model.read[0] == model.built[0]
    for before, now, read in zip(model.built, model.built[1:], model.read[1:], strict=False):
        assert now.startswith(before)  # the history only grew
        assert read == now[len(before) :]  # the reply it wrote is not kept: the history has it


@pytest.mark.parametrize("change", ["core", "rules", "tools"])
async def test_a_changed_beginning_is_read_again_from_where_it_changed(config: Config, change: str) -> None:
    model = StubModel([["ok"]])
    memory = FakeMemory(PERSONA)
    tools = host("remember", "hand_off")
    brain = brain_on(config, StubRuntime(model), core=PERSONA, tools=tools)
    brain._memory = memory  # noqa: SLF001
    await brain.start()
    try:
        await collect(brain, "hi")
        if change == "core":
            memory._core = PERSONA + "The owner likes tea."  # noqa: SLF001
        elif change == "rules":
            config.brain.offline = True
        else:
            del tools._tools["hand_off"]  # noqa: SLF001
        await collect(brain, "again")
    finally:
        await brain.close()
    honest(model)
    first, second = model.built
    assert model.read[1] == second[shared(first, second) :]
    assert shared(first, second) < len(first)


async def test_a_job_between_two_host_turns_takes_nothing_from_the_host(config: Config) -> None:
    model = StubModel([["Fine."]])
    runtime = StubRuntime(model)
    engine = engine_on(config, runtime)
    brain = brain_on(config, runtime, core=PERSONA)
    brain.engine = engine
    job = Request(core="RESIDENT " * 20, rules="Work carefully.", messages=[{"role": "user", "content": "Do the job."}], tools=[], max_tokens=10)
    try:
        await collect(brain, "hi")
        await engine.generate(job, "job")
        await engine.generate(job, "job")
        await collect(brain, "again")
    finally:
        await brain.close()
    honest(model)
    host_1, job_1, job_2, host_2 = model.built
    assert model.read[1] == job_1  # nothing shared with the host's prompt
    assert job_2 == job_1 and model.read[2] == job_1[-1:]  # its own entry, all but the last token
    assert model.read[3] == host_2[len(host_1) :]  # the host's entry was still there
    assert "RESIDENT" not in host_2 and "PERSONA" not in job_1


async def test_a_resident_job_and_the_host_interleaved_never_mix(config: Config) -> None:
    """Two conversations on one engine, turn by turn: each generation sees only its own."""
    model = StubModel([["Sure."]])
    runtime = StubRuntime(model)
    brain = brain_on(config, runtime, core=PERSONA)
    jobs = [
        Request(core=f"Resident {n}: " + "notes " * 30, rules="r", messages=[{"role": "user", "content": f"job {n}"}], tools=[], max_tokens=5)
        for n in range(3)
    ]
    try:
        for n, job in enumerate(jobs):
            await collect(brain, f"host turn {n}")
            await brain.engine.generate(job, "job")
            await brain.engine.generate(job, "job")
    finally:
        await brain.close()
    honest(model)
    for built in model.built:
        owners = {w for w in ("PERSONA", "Resident 0", "Resident 1", "Resident 2") if w in built}
        assert len(owners) <= 1


async def test_the_history_is_cut_in_blocks_so_the_beginning_holds(config: Config) -> None:
    config.brain.history_turns = 8  # type: ignore[attr-defined]
    model = StubModel([["ok"]])
    brain = brain_on(config, StubRuntime(model), core=PERSONA)
    await brain.start()
    try:
        for n in range(12):
            await collect(brain, f"message {n}")
    finally:
        await brain.close()
    honest(model)
    assert len(brain._history) == 6  # noqa: SLF001  (each 9th kept turn cuts them to the newest 6)
    cuts = [i for i, (a, b) in enumerate(zip(model.built, model.built[1:], strict=False), 1) if not b.startswith(a)]
    assert cuts == [9]
    for i in cuts:
        assert model.read[i] == model.built[i][shared(model.built[i - 1], model.built[i]) :]


async def test_an_interrupted_reply_leaves_a_true_cache(config: Config) -> None:
    model = StubModel([[f"w{i} " for i in range(100)], ["ok"]], delay=0.005)
    brain = brain_on(config, StubRuntime(model), core=PERSONA)
    await brain.start()
    try:
        async for event in brain.send("talk"):
            await brain.interrupt()
        await collect(brain, "next")
    finally:
        await brain.close()
    honest(model)
    assert model.read[1] == model.built[1][len(model.built[0]) :]


async def test_a_resident_job_on_the_local_model_reuses_its_own_steps(config: Config) -> None:
    call = json.dumps({"name": "remember", "arguments": {"text": "x"}})
    model = StubModel([[START, call, END], ["Done."]])
    runtime = StubRuntime(model)
    engine = engine_on(config, runtime)

    class Gate:
        def specs(self) -> list[Any]:
            return host("remember").specs()

        def line(self, name: str, args: dict[str, Any]) -> str:
            return name

        async def call(self, name: str, args: dict[str, Any]) -> Any:
            return await host("remember").call(name, args)

    class Desk:
        partial = ""

        class job:
            id = "j1"

        def step(self, kind: str, line: str) -> None: ...

    try:
        outcome = await work_local(engine, Gate(), Desk(), LocalSession("Resident notes " * 10, "Do it.", False, 4, False))  # type: ignore[arg-type]
    finally:
        await engine.close()
    assert outcome.status == "done" and outcome.result == "Done."
    honest(model)
    assert model.read[1] == model.built[1][shared(model.built[0], model.built[1]) :]
    assert shared(model.built[0], model.built[1]) >= len(model.built[0]) - 1


# ------------------------------------------------------------ the store itself


def kv(tokens: str, trimmable: bool = True) -> StubKV:
    k = StubKV(trimmable)
    k.tokens = [ord(c) for c in tokens]
    return k


def toks(text: str) -> list[int]:
    return [ord(c) for c in text]


def test_the_store_takes_the_longest_shared_entry_and_trims_it() -> None:
    caches = PromptCaches()
    base = "s" * MIN_SHARED
    caches.keep(toks(base + "AAAA"), kv(base + "AAAA"), "host")
    caches.keep(toks(base + "AB"), kv(base + "AB"), "job")
    got, known = caches.take(toks(base + "AAAB"), lambda: StubKV())
    assert known == MIN_SHARED + 3 and got.tokens == toks(base + "AAA") and len(caches) == 1


def test_the_store_leaves_alone_what_shares_only_the_opening() -> None:
    caches = PromptCaches()
    caches.keep(toks("x" * 200), kv("x" * 200), "host")
    got, known = caches.take(toks("x" * (MIN_SHARED - 1) + "y" * 100), lambda: StubKV())
    assert known == 0 and got.tokens == [] and len(caches) == 1


def test_the_store_never_hands_out_a_whole_prompt() -> None:
    caches = PromptCaches()
    caches.keep(toks("p" * 100), kv("p" * 100), "host")
    got, known = caches.take(toks("p" * 100), lambda: StubKV())
    assert known == 99 and len(got.tokens) == 99  # the last token is read to give the first word


def test_an_untrimmable_cache_is_used_only_when_it_all_fits() -> None:
    caches = PromptCaches()
    caches.keep(toks("p" * 100), kv("p" * 100, trimmable=False), "host")
    _, known = caches.take(toks("p" * 100 + "more"), lambda: StubKV())
    assert known == 100
    caches.keep(toks("p" * 100), kv("p" * 100, trimmable=False), "host")
    got, known = caches.take(toks("p" * 90 + "other"), lambda: StubKV())
    assert known == 0 and got.tokens == [] and len(caches) == 0  # it could not be cut back: dropped


def test_a_cache_that_does_not_hold_its_tokens_is_not_kept() -> None:
    caches = PromptCaches()
    caches.keep(toks("p" * 100), kv("p" * 99), "host")
    assert len(caches) == 0


def test_the_store_is_bounded_and_drops_jobs_before_the_host() -> None:
    caches = PromptCaches(max_entries=3, max_bytes=10_000)
    caches.keep(toks("h" * 100), kv("h" * 100), "host")
    for n in range(4):
        caches.keep(toks(str(n) * 100), kv(str(n) * 100), "job")
    assert len(caches) == 3
    assert caches.take(toks("h" * 100 + "!"), lambda: StubKV())[1] == 100  # the host's stayed
    assert caches.take(toks("0" * 100 + "!"), lambda: StubKV())[1] == 0  # the oldest job's went
    small = PromptCaches(max_bytes=2_500)
    small.keep(toks("h" * 100), kv("h" * 100), "host")
    small.keep(toks("j" * 100), kv("j" * 100), "job")
    small.keep(toks("k" * 100), kv("k" * 100), "job")
    assert small.nbytes <= 2_500 and small.take(toks("h" * 101), lambda: StubKV())[1] == 100


# ------------------------------------------------------------ loading when wanted, keeping it


def statuses(engine: LocalEngine) -> list[Status]:
    seen: list[Status] = []
    engine.on_change = lambda: seen.append(engine.status())
    return seen


async def test_offline_mode_loads_at_once_and_a_turn_waits_for_that_load(config: Config) -> None:
    config.brain.offline = True
    model = StubModel([["Hi."]])
    runtime = StubRuntime(model)
    runtime.hold = threading.Event()
    brain = brain_on(config, runtime, core=PERSONA)
    seen = statuses(brain.engine)
    await brain.start()  # starts the load
    try:
        await asyncio.to_thread(runtime.loading.wait, 2)
        assert brain.engine.status().state == "loading"
        turn = asyncio.create_task(collect(brain, "hi"))
        await asyncio.sleep(0.05)
        assert not turn.done()
        runtime.hold.set()
        events = await turn
    finally:
        await brain.close()
    assert said(events) == "Hi." and runtime.loads == 1
    states = [s.state for s in seen]
    assert states.index("loading") < states.index("ready")
    assert seen[-1].state == "unloaded"  # closed
    ready = next(s for s in seen if s.state == "ready")
    assert ready.weights_bytes == model.weights_bytes


async def test_the_state_the_window_gets_names_the_load(config: Config) -> None:
    config.brain.offline = True
    runtime = StubRuntime(StubModel([["Hi."]]))
    runtime.hold = threading.Event()
    bus = Bus()
    engine = engine_on(config, runtime, bus)
    sub = bus.subscribe({BrainMode.TYPE})
    engine.on_change = lambda: bus.publish(mode(config, "local", engine))
    task = engine.follow()
    await asyncio.to_thread(runtime.loading.wait, 2)
    await asyncio.sleep(0)
    runtime.hold.set()
    await task
    await engine.close()
    events = []
    while not sub._queue.empty():  # noqa: SLF001
        events.append(sub._queue.get_nowait())  # noqa: SLF001
    loading = next(e for e in events if e.local_state == "loading")
    assert loading.local_model == config.brain.local_model and loading.offline
    assert any(e.local_state == "ready" and e.local_bytes == 2_000_000 for e in events)


async def test_a_failed_load_is_said_once_and_shown(config: Config) -> None:
    config.brain.offline = True
    runtime = StubRuntime(StubModel([["x"]]))
    runtime.fail = MemoryError("too big")
    bus = Bus()
    sub = bus.subscribe({Notice.TYPE})
    brain = brain_on(config, runtime, bus=bus)
    await brain.start()
    try:
        await brain.engine.follow()
        status = brain.engine.status()
        [error] = await collect(brain)
    finally:
        await brain.close()
    message = cannot_load(config.brain.local_model, MemoryError())
    assert status.state == "failed" and status.problem == message
    assert error.message == message and "Settings, under Models" in message  # type: ignore[union-attr]
    assert sub._queue.get_nowait().text == message  # noqa: SLF001
    assert sub._queue.empty()  # noqa: SLF001  (not again for the turn's own try)


async def test_offline_keeps_the_model_loaded(config: Config) -> None:
    config.brain.offline = True
    config.brain.local_idle_unload_s = 0.02
    runtime = StubRuntime(StubModel([["Hi."]]))
    brain = brain_on(config, runtime)
    await brain.start()
    try:
        await collect(brain)
        await asyncio.sleep(0.1)
        assert runtime.releases == 0 and brain.engine.status().state == "ready"
        config.brain.offline = False  # back to Claude: the model is only the fallback now
        await brain.engine.follow()
        await asyncio.sleep(0.1)
        assert runtime.releases == 1 and brain.engine.status().state == "unloaded"
    finally:
        await brain.close()
    assert runtime.loads == 1


async def test_always_keeps_the_fallback_ready(config: Config) -> None:
    config.brain.local_idle_unload_s = 0.02
    config.brain.local_keep_loaded = "always"
    runtime = StubRuntime(StubModel([["Hi."]]))
    brain = brain_on(config, runtime)
    await brain.start()
    try:
        await collect(brain)
        await asyncio.sleep(0.1)
        assert runtime.releases == 0
    finally:
        await brain.close()


async def test_not_offline_nothing_loads_before_a_turn(config: Config) -> None:
    runtime = StubRuntime(StubModel([["Hi."]]))
    brain = brain_on(config, runtime)
    await brain.start()
    try:
        await brain.engine.follow()
        assert runtime.loads == 0
    finally:
        await brain.close()


async def test_a_new_model_is_loaded_only_after_the_old_one_is_freed(config: Config) -> None:
    config.brain.offline = True
    order: list[str] = []

    class Tracked(StubRuntime):
        def __init__(self, name: str) -> None:
            super().__init__(StubModel([[name]]))
            self.name = name

        def load(self, path: Any) -> StubModel:
            order.append(f"load {self.name}")
            return super().load(path)

        def release(self) -> None:
            order.append(f"free {self.name}")
            super().release()

    def make(cfg: Config, bus: Bus, backend: str, repo: str) -> MlxBackend:
        return MlxBackend(cfg, bus, repo, runtime=Tracked(repo))

    engine = LocalEngine(config, Bus(), factory=make)
    old = config.brain.local_model
    await engine.follow()
    config.brain.local_model = "mlx-community/Qwen3-8B-4bit"
    await engine.follow()
    await engine.close()
    assert order == [f"load {old}", f"free {old}", "load mlx-community/Qwen3-8B-4bit", "free mlx-community/Qwen3-8B-4bit"]


async def test_a_long_prompt_is_shown_while_it_is_read(config: Config) -> None:
    model = StubModel([["ok"]])
    brain = brain_on(config, StubRuntime(model), core="P" * (READING_SHOWN + 100))
    seen = statuses(brain.engine)
    await brain.start()
    try:
        await collect(brain, "hi")
        await collect(brain, "short")
    finally:
        await brain.close()
    reading = [s.reading for s in seen if s.reading is not None]
    assert reading and reading[0][0] == 0 and reading[0][1] >= READING_SHOWN
    assert len(reading) == 1  # the second turn read a few tokens: nothing to show
    assert seen[-1].reading is None


async def test_the_kept_prompts_memory_is_reported(config: Config) -> None:
    model = StubModel([["Hi."]])
    brain = brain_on(config, StubRuntime(model), core=PERSONA)
    await brain.start()
    try:
        await collect(brain)
        status = brain.engine.status()
    finally:
        await brain.close()
    assert status.cache_bytes == 10 * (len(model.built[0]) + 1)  # the prompt and the one token said
