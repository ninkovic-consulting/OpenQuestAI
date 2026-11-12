"""What a reconnecting window needs to redraw itself, served by `/api/state`.

Follows the bus: the current conversational state, gate requests still
waiting for an answer, and the most recent notices (including the ones
published at startup, before any window was connected).
"""

from __future__ import annotations

import asyncio
from collections import deque
from typing import Any

from vision.core.bus import Bus
from vision.core.events import (
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
        self._sub = bus.subscribe(
            {StateChanged.TYPE, GateRequest.TYPE, GateResolved.TYPE, Notice.TYPE}
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

    async def _follow(self) -> None:
        async for event in self._sub:
            self.apply(event)

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "gate_pending": [req.to_envelope() for req in self.gate_pending.values()],
            "notices": [notice.to_envelope() for notice in self.notices],
        }
