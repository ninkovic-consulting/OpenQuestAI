"""The assistant's automation tools, through the real gate: each tool, notices, audit, tiers."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from scheduler_fakes import BERLIN, FakeClock

from vision.core.bus import Bus, Subscription
from vision.core.config import Config
from vision.core.events import GateDecision, GateRequest, Notice
from vision.gate import make_tool_host
from vision.gate.gate import ToolGate
from vision.scheduler import Automations, build_tools
from vision.testing.fakes import FakeMemory

NAMES = [
    "create_automation",
    "list_automations",
    "update_automation",
    "pause_automation",
    "resume_automation",
    "run_automation",
    "delete_automation",
]


@dataclass
class Rig:
    gate: ToolGate
    automations: Automations
    memory: FakeMemory
    bus: Bus
    notices: Subscription


@pytest.fixture
async def rig(config: Config) -> AsyncIterator[Rig]:
    bus = Bus()
    automations = Automations(config, bus, clock=FakeClock(), zone=lambda: BERLIN)
    await automations.start()
    memory = FakeMemory()
    gate = make_tool_host(config, bus, memory, build_tools(automations))
    assert isinstance(gate, ToolGate)
    async with bus.subscribe({Notice.TYPE}) as notices:
        yield Rig(gate, automations, memory, bus, notices)


async def texts(sub: Subscription) -> list[str]:
    """The notices published so far."""
    out = []
    while True:
        try:
            event = await asyncio.wait_for(sub.get(), 0.01)
        except TimeoutError:
            return out
        assert isinstance(event, Notice)
        out.append(event.text)


async def create_stretch(rig: Rig) -> str:
    result = await rig.gate.call(
        "create_automation",
        {"name": "Stretch", "instruction": "Remind the user to stretch.", "schedule": {"kind": "once", "in_minutes": 20}},
    )
    assert result.ok, result.content
    return rig.automations.find("Stretch").id


def test_the_tools_sit_after_the_five_with_their_tiers(rig: Rig, config: Config) -> None:
    names = [s.name for s in rig.gate.specs()]
    assert names == ["remember", "recall", "open_app", "open_url", "shell", *NAMES]
    tiers = {n: config.gate.tiers[n] for n in NAMES}
    assert tiers == {n: ("ask" if n == "delete_automation" else "free") for n in NAMES}
    create = next(s for s in rig.gate.specs() if s.name == "create_automation")
    assert '"every weekday at nine"' in create.description
    assert '"in twenty minutes"' in create.description


async def test_create_schedules_it_and_says_so(rig: Rig) -> None:
    result = await rig.gate.call(
        "create_automation",
        {"name": "Stretch", "instruction": "Remind the user to stretch.", "schedule": {"kind": "once", "in_minutes": 20}, "speak": False},
    )
    assert result.ok
    a = rig.automations.find("stretch")
    assert a.schedule == {"kind": "once", "at": "2026-11-12T14:20"} and a.speak is False
    assert "next Thu 12 Nov 2026 at 14:20" in result.content
    assert await texts(rig.notices) == ['Scheduled "Stretch": once on Thu 12 Nov 2026 at 14:20.']
    audit = rig.memory.audits[-1]
    assert audit.tool == "create_automation" and audit.decision == "allow" and audit.tier == "free"


async def test_create_refuses_with_the_reason(rig: Rig) -> None:
    result = await rig.gate.call(
        "create_automation",
        {"name": "Late", "instruction": "x", "schedule": {"kind": "once", "at": "2026-11-12T13:00"}},
    )
    assert not result.ok and "has already passed; it is now 2026-11-12T14:00" in result.content
    assert rig.automations.all() == []


async def test_list_starts_with_the_time_now(rig: Rig) -> None:
    empty = await rig.gate.call("list_automations", {})
    assert empty.content.startswith("Local time now: Thursday 12 November 2026, 14:00 (Europe/Berlin).")
    await create_stretch(rig)
    listed = await rig.gate.call("list_automations", {})
    assert '"Stretch": once on Thu 12 Nov 2026 at 14:20, next Thu 12 Nov 2026 at 14:20, spoken.' in listed.content


async def test_update_pause_resume_and_run_now(rig: Rig) -> None:
    automation_id = await create_stretch(rig)
    await texts(rig.notices)
    changed = await rig.gate.call(
        "update_automation", {"automation": "Stretch", "schedule": {"kind": "daily", "time": "16:00"}}
    )
    assert changed.ok and rig.automations.find(automation_id).schedule == {"kind": "daily", "time": "16:00"}
    assert (await rig.gate.call("pause_automation", {"automation": automation_id})).ok
    assert rig.automations.find(automation_id).paused
    assert (await rig.gate.call("resume_automation", {"automation": "stretch"})).ok
    assert not rig.automations.find(automation_id).paused
    assert (await rig.gate.call("run_automation", {"automation": automation_id})).ok
    assert list(rig.automations.manual) == [automation_id]
    assert await texts(rig.notices) == [
        'Changed "Stretch": every day at 16:00.',
        'Paused "Stretch".',
        'Resumed "Stretch".',
        'Running "Stretch" now.',
    ]
    missing = await rig.gate.call("pause_automation", {"automation": "Nothing"})
    assert not missing.ok and "list_automations" in missing.content


async def test_delete_asks_first_naming_the_automation(rig: Rig) -> None:
    await create_stretch(rig)
    await texts(rig.notices)
    requests = rig.bus.subscribe({GateRequest.TYPE})

    async def approve() -> None:
        request = await requests.get()
        assert isinstance(request, GateRequest)
        assert request.summary == "Delete an automation"
        assert request.detail == '"Stretch", once on Thu 12 Nov 2026 at 14:20'
        rig.bus.publish(GateDecision(id=request.id, decision="allow"))

    answering = asyncio.create_task(approve())
    result = await rig.gate.call("delete_automation", {"automation": "Stretch"})
    await answering
    requests.close()
    assert result.ok and rig.automations.all() == []
    assert await texts(rig.notices) == ['Removed "Stretch" (once on Thu 12 Nov 2026 at 14:20).']
    assert rig.memory.audits[-1].decision == "allow" and rig.memory.audits[-1].tier == "ask"


async def test_delete_declined_keeps_it(rig: Rig) -> None:
    await create_stretch(rig)
    requests = rig.bus.subscribe({GateRequest.TYPE})

    async def decline() -> None:
        request = await requests.get()
        assert isinstance(request, GateRequest)
        rig.bus.publish(GateDecision(id=request.id, decision="deny"))

    answering = asyncio.create_task(decline())
    result = await rig.gate.call("delete_automation", {"automation": "Stretch"})
    await answering
    requests.close()
    assert not result.ok and len(rig.automations.all()) == 1


async def test_tiers_stay_configurable(rig: Rig, config: Config) -> None:
    config.gate.tiers["create_automation"] = "never"
    result = await rig.gate.call(
        "create_automation", {"name": "X", "instruction": "x", "schedule": {"kind": "daily", "time": "09:00"}}
    )
    assert not result.ok and rig.automations.all() == []
