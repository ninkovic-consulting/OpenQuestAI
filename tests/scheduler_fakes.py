"""A clock that moves only when a test says so, and helpers for the scheduler tests."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")
START = datetime(2026, 11, 12, 14, 0, tzinfo=BERLIN).timestamp()


class FakeClock:
    def __init__(self, start: float = START) -> None:
        self.t = start
        self._moved = asyncio.Event()
        self.asleep = False
        """True while the runner sleeps on its own (not waiting for the assistant)."""

    def now(self) -> float:
        return self.t

    async def sleep(self, seconds: float, wake: asyncio.Event) -> None:
        target = self.t + seconds
        while self.t < target and not wake.is_set():
            moved = self._moved
            waits = {asyncio.ensure_future(moved.wait()), asyncio.ensure_future(wake.wait())}
            self.asleep = True
            try:
                await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
            finally:
                self.asleep = False
                for w in waits:
                    w.cancel()
        wake.clear()

    def advance(self, seconds: float) -> None:
        self.t += seconds
        moved, self._moved = self._moved, asyncio.Event()
        moved.set()


async def until(check: Callable[[], bool], timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not check():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.005)
