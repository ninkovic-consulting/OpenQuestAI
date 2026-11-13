"""`Presence`: whether the owner is at the Mac now, kept current and announced.

The owner is away when the screen is locked, when the main display sleeps,
or when nothing has come from the keyboard, the mouse or the owner's voice
at the Mac for `[presence] away_after_s` (read on every check, so a change
in Settings applies at once). Speech counts because the owner can talk to
the assistant for a long while without touching anything. A message from
the phone does not: the owner is then plainly not at the Mac.

It reads every `poll_s` and on demand (`check`), so a decision about the
phone is made on a fresh reading rather than one up to `poll_s` old. A
change publishes `presence`. When the Mac will not say, the owner counts
as present, the event says `known: false`, and the status says so.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.events import InputText, PresenceChanged, PresenceReason, UserUtterance
from vision.presence.reader import Reader, Reading

POLL_S = 5.0


@dataclass(frozen=True, slots=True)
class Seen:
    """The owner's presence at one moment."""

    away: bool
    known: bool
    reason: PresenceReason | None
    since: float
    """When this state began, Unix seconds."""
    idle_s: float | None
    """Seconds since the owner's last keyboard, mouse or spoken input at the Mac."""


class Presence:
    def __init__(
        self,
        config: Config,
        bus: Bus,
        reader: Reader,
        *,
        clock: Callable[[], float] = time.time,
        poll_s: float = POLL_S,
    ) -> None:
        self._config = config
        self._bus = bus
        self._reader = reader
        self._clock = clock
        self._poll_s = poll_s
        self._heard_at = -math.inf
        self.seen = Seen(away=False, known=False, reason=None, since=clock(), idle_s=None)
        self._announced: dict[str, Any] | None = None

    @property
    def away_after_s(self) -> float:
        return self._config.presence.away_after_s

    def check(self) -> Seen:
        """Read now; announce a change. Cheap enough to call before every decision."""
        now = self._clock()
        reading = self._reader.read()
        idle = self._idle(reading, now)
        reason = _reason(reading, idle, self.away_after_s)
        away, known = reason is not None, reading.known
        old = self.seen
        if away == old.away:
            since = old.since  # only the reason or `known` changed
        elif reason == "idle" and idle is not None:
            since = min(now, now - idle + self.away_after_s)  # when the time ran out, not when it was seen
        else:
            since = now
        self.seen = Seen(away, known, reason, since, idle)
        event = self.event()
        if event.data() != self._announced:  # the state, its reason, or the away time changed
            self._announced = event.data()
            self._bus.publish(event)
        return self.seen

    def heard(self) -> None:
        """The owner spoke or typed to the assistant at the Mac."""
        self._heard_at = self._clock()
        self.check()

    def event(self) -> PresenceChanged:
        s = self.seen
        return PresenceChanged(away=s.away, known=s.known, reason=s.reason, since=s.since, away_after_s=self.away_after_s)

    def view(self) -> dict[str, Any]:
        """The shape of the `presence` event's data, for `/api/state` and `/api/phone`."""
        return self.event().data()

    async def run(self) -> None:
        """Check every `poll_s` and on every word to the assistant at the Mac, until cancelled."""
        self.check()
        async with self._bus.subscribe({UserUtterance.TYPE, InputText.TYPE}) as sub:
            while True:
                try:
                    event = await asyncio.wait_for(sub.get(), self._poll_s)
                except TimeoutError:
                    self.check()
                    continue
                if not (isinstance(event, UserUtterance) and event.source == "phone"):
                    self.heard()

    def _idle(self, reading: Reading, now: float) -> float | None:
        heard = now - self._heard_at
        if reading.idle_s is None:
            return None
        return min(reading.idle_s, heard)


def _reason(reading: Reading, idle: float | None, away_after_s: float) -> PresenceReason | None:
    if reading.locked:
        return "locked"
    if reading.asleep:
        return "asleep"
    if idle is not None and idle >= away_after_s:
        return "idle"
    return None
