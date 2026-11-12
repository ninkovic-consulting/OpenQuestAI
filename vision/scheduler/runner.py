"""The runner: sleeps until the next automation is due, then runs it as a turn.

One run at a time, and only while the assistant is idle: a due run waits
while a turn is in progress, someone is talking, or a gate request waits.
Runs asked for "now" go first, then due runs, earliest first.

A run that is late by more than `[automations] missed_grace_s` (the daemon
was off, or the Mac asleep) is not made up: it is recorded as missed and the
automation moves on to its next time. Within the grace period it runs once,
however many times it was missed, recorded as a catch-up.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from vision.core.config import Config
from vision.scheduler.model import Automation, RunResult, RunStatus, Trigger
from vision.scheduler.service import Automations

log = logging.getLogger(__name__)

MAX_SLEEP_S = 60.0
BUSY_POLL_S = 1.0
CATCH_UP_AFTER_S = 60.0
"""A run later than this was missed while the daemon was off or the Mac asleep."""

Execute = Callable[[Automation], Awaitable[tuple[RunStatus, str]]]
"""Runs an automation's turn; answers its status and reply."""


class Runner:
    def __init__(
        self, config: Config, automations: Automations, execute: Execute, busy: Callable[[], bool]
    ) -> None:
        self._config = config
        self._automations = automations
        self._execute = execute
        self._busy = busy
        self._idle_wait = asyncio.Event()

    async def run(self) -> None:
        """Run until cancelled. The first pass makes up runs missed while the daemon was off."""
        while True:
            await self.tick()
            await self._sleep()

    async def tick(self) -> None:
        """Run whatever was asked for now, then whatever is due."""
        autos, clock = self._automations, self._automations.clock
        while autos.manual:
            a = autos.get(autos.manual.popleft())
            if a is not None:
                await self._fire(a, "manual")
        for a in autos.due(clock.now()):
            now = clock.now()
            if a.paused or a.finished or a.next_run is None or a.next_run > now:
                continue  # changed while an earlier run was going
            if autos.get(a.id) is not a:
                continue  # deleted meanwhile
            late = now - a.next_run
            if late > self._config.automations.missed_grace_s:
                log.info("automation %s (%s) missed by %.0f s; skipped", a.id, a.name, late)
                await autos.skip(a, now)
                continue
            await self._fire(a, "catch_up" if late > CATCH_UP_AFTER_S else "schedule")

    async def _fire(self, a: Automation, trigger: Trigger) -> None:
        clock = self._automations.clock
        while self._busy():
            await clock.sleep(BUSY_POLL_S, self._idle_wait)
        started = clock.now()
        log.info("automation %s (%s) starts (%s)", a.id, a.name, trigger)
        self._automations.begin(a)
        try:
            status, reply = await self._execute(a)
        except Exception as exc:
            log.exception("automation %s failed", a.id)
            status, reply = "failed", f"The run failed ({type(exc).__name__})."
        except asyncio.CancelledError:
            self._automations.running = None
            raise
        log.info("automation %s (%s) ended: %s", a.id, a.name, status)
        await self._automations.finish(a, RunResult(started, clock.now(), status, reply, trigger))

    async def _sleep(self) -> None:
        autos = self._automations
        due = autos.next_due()
        delay = MAX_SLEEP_S if due is None else min(MAX_SLEEP_S, due - autos.clock.now())
        if autos.manual:
            delay = 0.0
        await autos.clock.sleep(max(0.0, delay), autos.wake)
