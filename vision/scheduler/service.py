"""The automations: kept in memory, saved on every change, and announced on the bus.

`Automations` is what the routes, the tools and the runner share. Every
change is saved to `automations.json`, publishes `automation.changed` and
wakes the runner, so a new next run is picked up at once. Refusals raise
`AutomationError` (or `NotFound`) with a message for people.
"""

from __future__ import annotations

import asyncio
import math
import re
import uuid
from collections import deque
from collections.abc import Callable
from datetime import datetime, tzinfo
from typing import Any

from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.events import AutomationChange, AutomationChanged, AutomationFinished, AutomationStarted
from vision.core.localtime import local_zone
from vision.scheduler import store
from vision.scheduler.clock import Clock, SystemClock
from vision.scheduler.model import (
    INSTRUCTION_MAX,
    MAX_AUTOMATIONS,
    NAME_MAX,
    Automation,
    RunResult,
    reply_start,
)
from vision.scheduler.schedule import ScheduleError, next_run, normalize
from vision.scheduler.words import describe

FIELDS = frozenset({"name", "instruction", "schedule", "speak", "paused"})
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class AutomationError(ValueError):
    """A change that cannot be made; the message is for people."""


class NotFound(LookupError):
    def __init__(self, ref: str) -> None:
        super().__init__(f"There is no automation called {ref!r}.")


class Automations:
    def __init__(
        self,
        config: Config,
        bus: Bus,
        *,
        clock: Clock | None = None,
        zone: Callable[[], tzinfo] = local_zone,
    ) -> None:
        self.config = config
        self.bus = bus
        self.clock: Clock = clock or SystemClock()
        self.zone = zone
        self.path = store.path_for(config)
        self._items: dict[str, Automation] = {}
        self._lock = asyncio.Lock()
        self.wake = asyncio.Event()
        """Set on every change; the runner sleeps on it."""
        self.manual: deque[str] = deque()
        """Automations asked to run now, oldest first."""
        self.running: str | None = None

    # ------------------------------------------------------------ reading

    async def start(self) -> None:
        self._items = {a.id: a for a in await asyncio.to_thread(store.load, self.path)}

    async def reload(self) -> None:
        """Read the file again (after a reset or a restore) and tell the window."""
        async with self._lock:
            self._items = {a.id: a for a in await asyncio.to_thread(store.load, self.path)}
            self.manual.clear()
        self.bus.publish(AutomationChanged(id="", change="reloaded"))
        self.wake.set()

    def all(self) -> list[Automation]:
        return sorted(self._items.values(), key=lambda a: (a.created_at, a.id))

    def find(self, ref: str) -> Automation:
        """By id, or else by name (ignoring case)."""
        if ref in self._items:
            return self._items[ref]
        wanted = ref.strip().casefold()
        for a in self._items.values():
            if a.name.casefold() == wanted:
                return a
        raise NotFound(ref)

    def view(self, a: Automation) -> dict[str, Any]:
        """The shape of `GET /api/automations` and of `automation.changed`."""
        return {**a.to_dict(), "words": describe(a.schedule), "running": a.id == self.running}

    def now_local(self) -> datetime:
        return datetime.fromtimestamp(self.clock.now(), self.zone())

    # ------------------------------------------------------------ changing

    async def create(self, body: dict[str, Any]) -> Automation:
        async with self._lock:
            if len(self._items) >= MAX_AUTOMATIONS:
                raise AutomationError(
                    f"There are already {MAX_AUTOMATIONS} automations, the most allowed. "
                    "Delete one first."
                )
            missing = [f for f in ("name", "instruction", "schedule") if f not in body]
            if missing:
                raise AutomationError(f"An automation needs {', '.join(missing)}.")
            fields = self._check(body, None)
            now = self.clock.now()
            a = Automation(
                id=uuid.uuid4().hex[:8],
                name=fields["name"],
                instruction=fields["instruction"],
                schedule=fields["schedule"],
                speak=fields.get("speak", True),
                created_at=now,
                updated_at=now,
                anchor=now,
                next_run=None,
                paused=fields.get("paused", False),
            )
            self._plan(a, now)
            self._items[a.id] = a
            await self._saved(a, "created")
            return a

    async def update(self, ref: str, body: dict[str, Any]) -> Automation:
        async with self._lock:
            a = self.find(ref)
            fields = self._check(body, a)
            now = self.clock.now()
            for key in ("name", "instruction", "speak"):
                if key in fields:
                    setattr(a, key, fields[key])
            if "schedule" in fields and fields["schedule"] != a.schedule:
                a.schedule, a.anchor, a.finished = fields["schedule"], now, False
            if "paused" in fields:
                a.paused = fields["paused"]
            a.updated_at = now
            self._plan(a, now)
            await self._saved(a, "updated")
            return a

    async def delete(self, ref: str) -> Automation:
        async with self._lock:
            a = self._items.pop(self.find(ref).id)
            await asyncio.to_thread(store.save, self.path, self.all())
            self.bus.publish(AutomationChanged(id=a.id, change="deleted"))
            self.wake.set()
            return a

    def request_run(self, ref: str) -> Automation:
        """Queue a run now, outside the schedule, even when paused or finished."""
        a = self.find(ref)
        if a.id not in self.manual and a.id != self.running:
            self.manual.append(a.id)
            self.wake.set()
        return a

    def _check(self, body: dict[str, Any], current: Automation | None) -> dict[str, Any]:
        unknown = set(body) - FIELDS
        if unknown:
            raise AutomationError(f"An automation has no {', '.join(sorted(unknown))}.")
        out: dict[str, Any] = {}
        if "name" in body:
            name = body["name"]
            if not isinstance(name, str) or not name.strip() or _CONTROL.search(name):
                raise AutomationError("The name must be a line of text.")
            name = " ".join(name.split())
            if len(name) > NAME_MAX:
                raise AutomationError(f"The name can be at most {NAME_MAX} characters.")
            clash = next(
                (a for a in self._items.values() if a.name.casefold() == name.casefold()), None
            )
            if clash is not None and clash is not current:
                raise AutomationError(f"There is already an automation called {clash.name!r}.")
            out["name"] = name
        if "instruction" in body:
            text = body["instruction"]
            if not isinstance(text, str) or not text.strip():
                raise AutomationError("The instruction must say what to do, in words.")
            if len(text.strip()) > INSTRUCTION_MAX:
                raise AutomationError(
                    f"The instruction can be at most {INSTRUCTION_MAX} characters; "
                    f"this one has {len(text.strip())}."
                )
            out["instruction"] = text.strip()
        for flag in ("speak", "paused"):
            if flag in body:
                if not isinstance(body[flag], bool):
                    raise AutomationError(f"{flag} must be true or false.")
                out[flag] = body[flag]
        if "schedule" in body:
            try:
                out["schedule"] = normalize(body["schedule"], self.now_local())
            except ScheduleError as exc:
                raise AutomationError(str(exc)) from None
        return out

    def _plan(self, a: Automation, now: float) -> None:
        """Work out the next run after a change: none while paused or finished."""
        if a.paused or a.finished:
            a.next_run = None
            return
        a.next_run = next_run(a.schedule, now, a.anchor, self.zone())
        if a.next_run is None:  # a once whose time passed while it was paused
            a.finished = True
            a.add_result(RunResult(now, now, "missed", "Its time passed while it was paused.", "schedule"))

    async def _saved(self, a: Automation, change: AutomationChange) -> None:
        await asyncio.to_thread(store.save, self.path, self.all())
        self.bus.publish(AutomationChanged(id=a.id, change=change, automation=self.view(a)))
        self.wake.set()

    # ------------------------------------------------------------ the runner's side

    def due(self, now: float) -> list[Automation]:
        """Active automations whose next run has come, earliest first."""
        found = [
            a
            for a in self._items.values()
            if not a.paused and not a.finished and a.next_run is not None and a.next_run <= now
        ]
        return sorted(found, key=lambda a: (a.next_run or 0.0, a.id))

    def next_due(self) -> float | None:
        times = [
            a.next_run
            for a in self._items.values()
            if not a.paused and not a.finished and a.next_run is not None
        ]
        return min(times, default=None)

    def get(self, automation_id: str) -> Automation | None:
        return self._items.get(automation_id)

    async def skip(self, a: Automation, now: float) -> None:
        """Record a run missed by more than the grace period, and move on."""
        assert a.next_run is not None
        late = max(1, math.floor((now - a.next_run) / 60))
        reason = f"Missed by {late} minute{'s' if late != 1 else ''} while the assistant was off."
        async with self._lock:
            a.add_result(RunResult(now, now, "missed", reason, "schedule"))
            self._advance(a, now)
            await self._saved(a, "updated")

    def begin(self, a: Automation) -> None:
        self.running = a.id
        self.bus.publish(AutomationStarted(id=a.id, name=a.name))
        self.bus.publish(AutomationChanged(id=a.id, change="updated", automation=self.view(a)))

    async def finish(self, a: Automation, result: RunResult) -> None:
        """Record a run's result; a scheduled run moves the automation to its next time."""
        self.running = None
        result.reply = reply_start(result.reply)
        self.bus.publish(
            AutomationFinished(id=a.id, name=a.name, status=result.status, reply=result.reply)
        )
        async with self._lock:
            if self._items.get(a.id) is not a:  # deleted while it ran
                return
            a.add_result(result)
            if result.trigger != "manual":
                self._advance(a, result.ended_at)
            await self._saved(a, "updated")

    def _advance(self, a: Automation, now: float) -> None:
        if a.schedule["kind"] == "once":
            a.finished, a.next_run = True, None
        else:
            a.next_run = next_run(a.schedule, now, a.anchor, self.zone())
