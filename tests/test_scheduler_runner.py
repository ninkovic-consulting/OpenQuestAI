"""The runner on a fake clock: due runs, a busy assistant, missed runs, once-only, run now."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest
from scheduler_fakes import BERLIN, FakeClock, until

from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.events import AutomationFinished, AutomationStarted
from vision.scheduler import Automations, Runner
from vision.scheduler.model import Automation, RunStatus


@dataclass
class Rig:
    clock: FakeClock
    automations: Automations
    runner: Runner
    bus: Bus
    ran: list[str] = field(default_factory=list)
    busy: bool = False
    answer: RunStatus = "ok"


@pytest.fixture
async def rig(config: Config) -> AsyncIterator[Rig]:
    bus = Bus()
    clock = FakeClock()
    automations = Automations(config, bus, clock=clock, zone=lambda: BERLIN)
    await automations.start()
    holder: dict[str, Rig] = {}

    async def execute(a: Automation) -> tuple[RunStatus, str]:
        holder["rig"].ran.append(a.name)
        return holder["rig"].answer, f"Did {a.name}."

    runner = Runner(config, automations, execute, lambda: holder["rig"].busy)
    holder["rig"] = Rig(clock, automations, runner, bus)
    yield holder["rig"]


async def running(rig: Rig) -> asyncio.Task[None]:
    task = asyncio.create_task(rig.runner.run())
    await until(lambda: rig.clock.asleep)
    return task


async def stop(task: asyncio.Task[None]) -> None:
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_a_due_run_runs_once_and_moves_on(rig: Rig) -> None:
    events = rig.bus.subscribe({AutomationStarted.TYPE, AutomationFinished.TYPE})
    a = await rig.automations.create(
        {"name": "Water", "instruction": "Remind me to drink water.", "schedule": {"kind": "interval", "every": 30, "unit": "minutes"}}
    )
    task = await running(rig)
    rig.clock.advance(29 * 60)
    await until(lambda: rig.clock.asleep)
    assert rig.ran == []
    rig.clock.advance(60)
    await until(lambda: rig.ran == ["Water"] and rig.clock.asleep)
    assert a.results[-1].status == "ok" and a.results[-1].trigger == "schedule"
    assert a.results[-1].reply == "Did Water."
    assert a.next_run == a.anchor + 3600
    await stop(task)
    started, finished = await events.get(), await events.get()
    assert isinstance(started, AutomationStarted) and started.name == "Water"
    assert isinstance(finished, AutomationFinished) and finished.status == "ok"


async def test_a_busy_assistant_makes_the_run_wait(rig: Rig) -> None:
    await rig.automations.create(
        {"name": "Tea", "instruction": "Say the tea is ready.", "schedule": {"kind": "once", "in_minutes": 1}}
    )
    rig.busy = True
    task = await running(rig)
    rig.clock.advance(60)
    for _ in range(5):
        await until(lambda: rig.clock.asleep)
        rig.clock.advance(1)
    assert rig.ran == []
    rig.busy = False
    rig.clock.advance(1)
    await until(lambda: rig.ran == ["Tea"])
    await stop(task)


async def test_once_only_is_kept_finished_and_not_repeated(rig: Rig) -> None:
    a = await rig.automations.create(
        {"name": "Stretch", "instruction": "Remind me to stretch.", "schedule": {"kind": "once", "in_minutes": 1}}
    )
    task = await running(rig)
    rig.clock.advance(60)
    await until(lambda: rig.ran == ["Stretch"] and rig.clock.asleep)
    assert a.finished and a.next_run is None
    rig.clock.advance(7 * 86400)
    await until(lambda: rig.clock.asleep)
    assert rig.ran == ["Stretch"]
    assert rig.automations.get(a.id) is a
    await stop(task)


async def test_missed_within_the_grace_period_runs_once_on_start(config: Config, rig: Rig) -> None:
    a = await rig.automations.create(
        {"name": "Hourly", "instruction": "Check the news.", "schedule": {"kind": "interval", "every": 10, "unit": "minutes"}}
    )
    # The daemon was off for 35 minutes: three runs were missed.
    rig.clock.advance(35 * 60)
    task = await running(rig)
    assert rig.ran == ["Hourly"]
    assert a.results[-1].trigger == "catch_up"
    assert a.next_run == a.anchor + 40 * 60
    await stop(task)


async def test_missed_beyond_the_grace_period_is_skipped_and_recorded(config: Config, rig: Rig) -> None:
    config.automations.missed_grace_s = 600
    daily = await rig.automations.create(
        {"name": "Morning", "instruction": "Read me the weather.", "schedule": {"kind": "daily", "time": "15:00"}}
    )
    once = await rig.automations.create(
        {"name": "Call", "instruction": "Remind me to call.", "schedule": {"kind": "once", "at": "2026-11-12T14:30"}}
    )
    rig.clock.advance(3 * 3600)  # off from 14:00 to 17:00
    task = await running(rig)
    assert rig.ran == []
    assert [r.status for r in daily.results] == ["missed"]
    assert "Missed by 120 minutes" in daily.results[0].reply
    assert daily.next_run is not None and daily.next_run > rig.clock.now()
    assert once.finished and once.results[-1].status == "missed"
    await stop(task)


async def test_paused_automations_do_not_run_and_run_now_still_works(rig: Rig) -> None:
    a = await rig.automations.create(
        {"name": "Quiet", "instruction": "Say hello.", "schedule": {"kind": "interval", "every": 1, "unit": "minutes"}, "paused": True}
    )
    task = await running(rig)
    rig.clock.advance(300)
    await until(lambda: rig.clock.asleep)
    assert rig.ran == [] and a.next_run is None
    rig.automations.request_run(a.id)
    await until(lambda: rig.ran == ["Quiet"] and rig.clock.asleep)
    assert a.results[-1].trigger == "manual" and a.next_run is None
    await rig.automations.update(a.id, {"paused": False})
    assert a.next_run == a.anchor + 360
    await stop(task)


async def test_a_run_that_needed_approval_is_recorded_so(rig: Rig) -> None:
    rig.answer = "needed_approval"
    a = await rig.automations.create(
        {"name": "Cleanup", "instruction": "Empty the downloads folder.", "schedule": {"kind": "once", "in_minutes": 1}}
    )
    task = await running(rig)
    rig.clock.advance(60)
    await until(lambda: bool(a.results))
    assert a.results[-1].status == "needed_approval"
    await stop(task)


async def test_runs_never_overlap(rig: Rig) -> None:
    gate = asyncio.Event()
    active: list[str] = []
    overlap: list[bool] = []

    async def slow(a: Automation) -> tuple[RunStatus, str]:
        overlap.append(bool(active))
        active.append(a.name)
        await gate.wait()
        active.remove(a.name)
        return "ok", ""

    runner = Runner(rig.automations.config, rig.automations, slow, lambda: False)
    for name in ("One", "Two"):
        await rig.automations.create(
            {"name": name, "instruction": "x", "schedule": {"kind": "once", "in_minutes": 1}}
        )
    task = asyncio.create_task(runner.run())
    await until(lambda: rig.clock.asleep)
    rig.clock.advance(60)
    await until(lambda: len(active) == 1)
    gate.set()
    await until(lambda: len(overlap) == 2 and not active)
    assert overlap == [False, False]
    await stop(task)
