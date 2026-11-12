"""The scheduler's clock: the time now, and a sleep that a change can cut short.

The runner never sleeps longer than a minute at a time, so a clock that jumps
(the Mac waking from sleep, the time being set) is noticed within a minute.
Tests use a fake clock that moves only when told to.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Protocol


class Clock(Protocol):
    def now(self) -> float:
        """Unix seconds."""
        ...

    async def sleep(self, seconds: float, wake: asyncio.Event) -> None:
        """Return after `seconds`, or as soon as `wake` is set (which it then clears)."""
        ...


class SystemClock:
    def now(self) -> float:
        return time.time()

    async def sleep(self, seconds: float, wake: asyncio.Event) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(wake.wait(), max(0.0, seconds))
        wake.clear()
