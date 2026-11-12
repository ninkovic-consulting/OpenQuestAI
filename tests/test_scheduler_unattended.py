"""An automation's run is a turn with nobody necessarily watching: the gate still decides."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from typing import Any

import pytest
from scheduler_fakes import BERLIN, FakeClock

from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.events import BrainName, GateRequest, GateResolved, UserUtterance, VisionReply
from vision.core.interfaces import BrainEvent, TextDelta, ToolHost, TurnDone
from vision.core.session import Session
from vision.gate.gate import ToolGate
from vision.gate.tools import CommandResult
from vision.gate.tools import build_tools as slice_one
from vision.scheduler import Automations, build_tools
from vision.testing.fakes import FakeMemory, FakeSpeaker

Call = tuple[str, dict[str, Any]]


class ToolBrain:
    """Calls the scripted tools through the host, then says what each answered."""

    def __init__(self, tools: ToolHost, calls: Sequence[Call]) -> None:
        self._tools = tools
        self._calls = list(calls)
        self.sent: list[str] = []

    @property
    def name(self) -> BrainName:
        return "fake"

    async def start(self) -> None: ...

    async def send(self, text: str, *, heavy: bool = False) -> AsyncIterator[BrainEvent]:
        self.sent.append(text)
        for name, args in self._calls:
            result = await self._tools.call(name, args)
            yield TextDelta(f"{name}: {'ok' if result.ok else 'refused'}. {result.content} ")
        yield TurnDone("fake-1", 1, 1, "end_turn")

    async def interrupt(self) -> None: ...

    async def close(self) -> None: ...


class Rig:
    def __init__(self, config: Config, calls: Sequence[Call]) -> None:
        config.gate.timeout_s = 0.2
        self.bus = Bus()
        self.automations = Automations(config, self.bus, clock=FakeClock(), zone=lambda: BERLIN)
        self.memory = FakeMemory()
        self.ran: list[list[str]] = []

        async def runner(argv: Sequence[str], **_: Any) -> CommandResult:
            self.ran.append(list(argv))
            return CommandResult(0, "done", False)

        self.gate = ToolGate(
            config, self.bus, self.memory, [*slice_one(config, self.memory, runner=runner), *build_tools(self.automations)]
        )
        self.brain = ToolBrain(self.gate, calls)
        self.speaker = FakeSpeaker()
        self.session = Session(self.bus, self.brain, self.speaker, self.memory, self.gate)

    async def run(self, speak: bool = True) -> tuple[Any, Any]:
        return await self.session.run_automation(
            "Clean up the downloads folder.", automation_id="a1", name="Cleanup", speak=speak
        )


async def test_an_unanswered_ask_does_not_run_and_needs_approval(config: Config) -> None:
    rig = Rig(config, [("shell", {"command": "rm -rf ~/Downloads/*"})])
    events = rig.bus.subscribe({GateRequest.TYPE, GateResolved.TYPE, UserUtterance.TYPE, VisionReply.TYPE})
    record, origin = await rig.run()
    assert origin.needed_approval
    assert rig.ran == []
    request = await events.get()
    assert isinstance(request, GateRequest)
    assert request.summary == 'Automation "Cleanup": Run a shell command'
    resolved = await events.get()
    assert isinstance(resolved, GateResolved) and resolved.decision == "timeout"
    reply = await events.get()
    assert isinstance(reply, VisionReply)  # no user.utterance: nobody said anything
    assert rig.memory.audits[-1].decision == "timeout"
    assert record.source == "automation" and record.user_text == "Clean up the downloads folder."
    assert "Nobody answered" in record.reply


async def test_an_answered_ask_runs(config: Config) -> None:
    rig = Rig(config, [("shell", {"command": "ls"})])
    requests = rig.bus.subscribe({GateRequest.TYPE})

    async def approve() -> None:
        request = await requests.get()
        assert isinstance(request, GateRequest)
        assert rig.gate.answer("yes")

    answering = asyncio.create_task(approve())
    record, origin = await rig.run()
    await answering
    assert not origin.needed_approval and rig.ran == [["/bin/sh", "-c", "ls"]]
    assert record.status == "ok"


async def test_free_tools_run_freely(config: Config) -> None:
    rig = Rig(config, [("remember", {"text": "The plants were watered."})])
    record, origin = await rig.run()
    assert rig.memory.notes[-1][1] == "The plants were watered."
    assert not origin.needed_approval and record.reply.startswith("remember: ok")


@pytest.mark.parametrize(
    "call",
    [
        ("create_automation", {"name": "More", "instruction": "x", "schedule": {"kind": "daily", "time": "09:00"}}),
        ("delete_automation", {"automation": "Keep"}),
        ("pause_automation", {"automation": "Keep"}),
        ("run_automation", {"automation": "Keep"}),
    ],
)
async def test_an_automation_cannot_change_automations(config: Config, call: Call) -> None:
    rig = Rig(config, [call])
    await rig.automations.create({"name": "Keep", "instruction": "x", "schedule": {"kind": "daily", "time": "09:00"}})
    requests = rig.bus.subscribe({GateRequest.TYPE})
    record, _ = await rig.run()
    assert "cannot create, change or delete automations" in record.reply
    assert [a.name for a in rig.automations.all()] == ["Keep"]
    assert not rig.automations.find("Keep").paused and not rig.automations.manual
    assert rig.memory.audits[-1].result == "refused during an automation"
    with pytest.raises(TimeoutError):  # refused before anyone was asked
        await asyncio.wait_for(requests.get(), 0.05)


async def test_the_brain_is_told_what_runs_and_when(config: Config) -> None:
    rig = Rig(config, [("list_automations", {})])
    await rig.run()
    sent = rig.brain.sent[0]
    assert sent.startswith('[Automation "Cleanup" is due now, ')
    assert sent.endswith("\nClean up the downloads folder.")


async def test_a_shown_only_run_is_not_spoken(config: Config) -> None:
    rig = Rig(config, [("list_automations", {})])
    record, _ = await rig.run(speak=False)
    assert rig.speaker.spoken == [] and record.reply
    await rig.run(speak=True)
    assert rig.speaker.spoken
