"""The daemon with its real parts wired together: gate answers, budget, house, lights, files."""

from __future__ import annotations

import asyncio
import stat
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from conftest import all_fakes, free_port, served

from vision.app import Daemon
from vision.core.bus import Bus, Subscription
from vision.core.config import Config
from vision.core.events import (
    BrainName,
    BudgetUpdate,
    Event,
    GateRequest,
    GateResolved,
    InputText,
    RoomState,
    StateChanged,
    VisionReply,
)
from vision.core.interfaces import (
    BrainEvent,
    TextDelta,
    ToolHost,
    ToolResult,
    ToolSpec,
    TurnDone,
)
from vision.core.session import Session
from vision.gate.gate import ToolGate
from vision.gate.tools import Tool
from vision.testing.fakes import FakeHouse, FakeMemory, FakeSpeaker


async def until(predicate: Callable[[], bool], timeout: float = 5) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


async def next_of(sub: Subscription, kind: type[Event], timeout: float = 5) -> Any:
    async with asyncio.timeout(timeout):
        async for event in sub:
            if isinstance(event, kind):
                return event
    raise AssertionError("subscription ended")


# ------------------------------------------------------------ gate answers


class ShellBrain:
    """Asks to run `echo hello` on every turn and says what came back."""

    def __init__(self, tools: ToolHost) -> None:
        self.tools = tools
        self.results: list[ToolResult] = []
        self.interrupts = 0

    @property
    def name(self) -> BrainName:
        return "fake"

    async def start(self) -> None:
        pass

    async def interrupt(self) -> None:
        self.interrupts += 1

    async def close(self) -> None:
        pass

    async def send(self, text: str, *, heavy: bool = False) -> AsyncIterator[BrainEvent]:
        result = await self.tools.call("shell", {"command": "echo hello"})
        self.results.append(result)
        yield TextDelta(result.content)
        yield TurnDone("fake-1", 1, 1, "end_turn")


@pytest.fixture
async def gated(config: Config) -> AsyncIterator[tuple[Bus, ShellBrain, FakeMemory, list[str]]]:
    config.gate.timeout_s = 5
    bus, memory, ran = Bus(), FakeMemory(), []

    async def shell(args: dict[str, Any]) -> str:
        ran.append(args["command"])
        return "hello"

    spec = ToolSpec("shell", "Run a command", {"type": "object", "properties": {}})
    gate = ToolGate(config, bus, memory, [Tool(spec, shell, "Run a shell command", "command")])
    brain = ShellBrain(gate)
    session = Session(bus, brain, FakeSpeaker(), memory, gate)
    task = asyncio.create_task(session.run())
    await asyncio.sleep(0)
    yield bus, brain, memory, ran
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_typed_yes_approves_the_waiting_request_without_interrupting(
    gated: tuple[Bus, ShellBrain, FakeMemory, list[str]],
) -> None:
    bus, brain, memory, ran = gated
    sub = bus.subscribe({GateRequest.TYPE, GateResolved.TYPE, VisionReply.TYPE})
    bus.publish(InputText(text="Run echo hello in the shell"))
    request = await next_of(sub, GateRequest)
    bus.publish(InputText(text="yes"))
    resolved = await next_of(sub, GateResolved)
    reply = await next_of(sub, VisionReply)

    assert (resolved.id, resolved.decision) == (request.id, "allow")
    assert ran == ["echo hello"]
    assert reply.text == "hello"
    assert brain.interrupts == 0
    await until(lambda: len(memory.turns) == 1)
    [turn] = memory.turns
    assert (turn.user_text, turn.status) == ("Run echo hello in the shell", "ok")
    [audit] = memory.audits
    assert (audit.tool, audit.decision, audit.request_id) == ("shell", "allow", request.id)


async def test_long_sentence_with_ok_does_not_approve(
    gated: tuple[Bus, ShellBrain, FakeMemory, list[str]],
) -> None:
    bus, brain, memory, ran = gated
    sub = bus.subscribe({GateRequest.TYPE, GateResolved.TYPE})
    bus.publish(InputText(text="Run echo hello in the shell"))
    first = await next_of(sub, GateRequest)
    bus.publish(InputText(text="ok so before that tell me what the weather is like"))
    resolved = await next_of(sub, GateResolved)
    assert (resolved.id, resolved.decision) == (first.id, "deny")
    assert ran == []
    # The sentence started a new turn, which asks again.
    second = await next_of(sub, GateRequest)
    assert second.id != first.id
    assert brain.interrupts == 1


# ------------------------------------------------------------ the daemon's own duties


async def test_startup_publishes_budget_and_runs_the_house(config: Config) -> None:
    d = Daemon(config, components=all_fakes)
    sub = d.bus.subscribe({BudgetUpdate.TYPE})
    await d.start()
    try:
        budget = await next_of(sub, BudgetUpdate)
        assert (budget.spent_usd, budget.cap_usd) == (0.0, 150.0)
        house = d.components.house
        assert isinstance(house, FakeHouse) and house.running
    finally:
        await d.stop()
    assert not house.running


async def test_hall_lights_follow_the_conversation(config: Config) -> None:
    d = Daemon(config, fake_brain=True)
    sub = d.bus.subscribe({RoomState.TYPE, StateChanged.TYPE, VisionReply.TYPE})
    await d.start()
    try:
        hall = lambda: next(r for r in d.components.house.plan()["rooms"] if r["id"] == "hall")  # noqa: E731
        d.bus.publish(InputText(text="Hello"))
        lights: list[RoomState] = []
        async with asyncio.timeout(5):
            async for event in sub:
                if isinstance(event, RoomState):
                    lights.append(event)
                    if event.state == "active":
                        assert hall()["state"] == "active"
                    else:
                        break
        assert [(e.room, e.state) for e in lights] == [("hall", "active"), ("hall", "idle")]
        assert hall()["state"] == "idle"
    finally:
        await d.stop()


async def test_host_persona_comes_from_the_house_on_a_fresh_home(config: Config) -> None:
    d = Daemon(config, fake_brain=True)
    await d.start()
    try:
        core = d.components.memory.core()
        assert "You are the host of this house" in core
        assert (config.paths.house / "agents" / "maker.md").is_file()
    finally:
        await d.stop()


async def test_seeding_never_overwrites_an_edited_persona(config: Config) -> None:
    mine = config.paths.house / "agents" / "host.md"
    mine.parent.mkdir(parents=True)
    mine.write_text("You are my own host.", encoding="utf-8")
    d = Daemon(config, fake_brain=True)
    await d.start()
    try:
        assert "You are my own host." in d.components.memory.core()
        assert "You are the host of this house" not in d.components.memory.core()
    finally:
        await d.stop()


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


async def test_private_files(config: Config) -> None:
    d = Daemon(config, fake_brain=True)
    sub = d.bus.subscribe({VisionReply.TYPE})
    await d.start()
    try:
        d.bus.publish(InputText(text="Hello"))
        await next_of(sub, VisionReply)
        home = config.paths.home
        assert mode(home) == 0o700
        assert mode(config.paths.token) == 0o600
        assert mode(config.paths.house_file) == 0o600
        assert mode(home / "budget.json") == 0o600
        db = config.paths.log_db
        for path in (db, db.with_name(db.name + "-wal"), db.with_name(db.name + "-shm")):
            assert path.exists() and mode(path) == 0o600, path
    finally:
        await d.stop()


async def test_existing_home_is_made_private(config: Config) -> None:
    config.paths.home.mkdir(mode=0o755)
    Daemon(config, components=all_fakes)
    assert mode(config.paths.home) == 0o700


async def test_state_lists_notices_like_the_notice_event(config: Config) -> None:
    config.paths.home.mkdir(parents=True)
    config.paths.house_file.write_text("this is = = not toml", encoding="utf-8")
    async with served(Daemon(config, fake_brain=True, port=free_port())) as d:
        headers = {"Authorization": f"Bearer {d.token}"}
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{d.port}", headers=headers) as c:
            notices: list[dict[str, Any]] = []

            async def broken_house_notice() -> dict[str, Any] | None:
                nonlocal notices
                notices = (await c.get("/api/state")).json()["notices"]
                return next((n for n in notices if "house.toml" in n["text"]), None)

            async with asyncio.timeout(5):
                while (found := await broken_house_notice()) is None:
                    await asyncio.sleep(0.05)
    assert set(found) == {"level", "text"}
    assert found["level"] == "warn"
    assert found["text"].startswith("Your house.toml was not applied.")
    assert all(set(n) == {"level", "text"} and n["text"] for n in notices)
