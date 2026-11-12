"""What a reconnecting window needs to redraw itself, served by `/api/state`.

Follows the bus: the current conversational state, gate requests still
waiting for an answer, the automation running now (`{"id", "name"}` or
null), and the most recent notices (including the ones published at
startup, before any window was connected).

Gate requests and notices are listed in the shape of their event's `data`
(`{"level": ..., "text": ...}` for a notice), the same shape the window gets
inside a `notice` or `gate.request` envelope on the socket.
"""

from __future__ import annotations

import asyncio
from collections import deque
from typing import Any

from vision.core.bus import Bus
from vision.core.events import (
    AutomationFinished,
    AutomationStarted,
    Event,
    GateRequest,
    GateResolved,
    Notice,
    State,
    StateChanged,
)

MAX_NOTICES = 20


class Snapshot:
    def __init__(self, bus: Bus) -> None:
        self.state: State = "idle"
        self.gate_pending: dict[str, GateRequest] = {}
        self.notices: deque[Notice] = deque(maxlen=MAX_NOTICES)
        self.automation: dict[str, str] | None = None
        self._sub = bus.subscribe(
            {
                StateChanged.TYPE,
                GateRequest.TYPE,
                GateResolved.TYPE,
                Notice.TYPE,
                AutomationStarted.TYPE,
                AutomationFinished.TYPE,
            }
        )
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._follow())

    async def stop(self) -> None:
        self._sub.close()
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    def apply(self, event: Event) -> None:
        match event:
            case StateChanged(state=state):
                self.state = state
            case GateRequest(id=request_id):
                self.gate_pending[request_id] = event
            case GateResolved(id=request_id):
                self.gate_pending.pop(request_id, None)
            case Notice():
                self.notices.append(event)
            case AutomationStarted(id=automation_id, name=name):
                self.automation = {"id": automation_id, "name": name}
            case AutomationFinished():
                self.automation = None

    async def _follow(self) -> None:
        async for event in self._sub:
            self.apply(event)

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "gate_pending": [req.data() for req in self.gate_pending.values()],
            "notices": [notice.data() for notice in self.notices],
            "automation": self.automation,
        }
