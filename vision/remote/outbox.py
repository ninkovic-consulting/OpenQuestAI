"""Sending to the phone once, and again only when it did not arrive.

Every message the assistant sends unasked has a key that names what it is
about (`job:<id>`, `turn:<id>`, `automation:<id>:<started>`, ...). A key is
sent at most once: a second message about the same thing is refused, so
nothing reaches the phone twice.

A message that cannot be sent now (Discord unreachable, the channel
reconnecting) is tried again after each of `RETRY_S`, then dropped with a
notice in the app. Nothing waits longer than that, so nothing piles up while
Discord is down and floods the phone later. A message whose owner unpaired
meanwhile is dropped quietly.

It also remembers when `send_to_phone` last messaged the phone, so the result
of the turn that used it is not sent again (`pinged_since`).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable
from typing import Literal

from vision.core.events import Notice
from vision.remote.link import Link
from vision.remote.text import clip
from vision.remote.transport import Unreachable

log = logging.getLogger(__name__)

RETRY_S = (5.0, 20.0, 60.0)
"""Waits before each new try; after the last one fails, the message is dropped."""
KEYS_KEPT = 500
PINGS_KEPT = 20
DROPPED = "Not sent to the phone"
"""The start of the notice for a dropped message; such a notice is never sent to the phone."""
REPLY_ROOM = 1500

Sent = Literal["sent", "retrying", "duplicate", "unpaired"]


class Outbox:
    def __init__(
        self,
        link: Link,
        *,
        retry_s: tuple[float, ...] = RETRY_S,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._link = link
        self.retry_s = retry_s
        """Waits before each new try (tests shorten them)."""
        self._clock = clock
        self._keys: deque[str] = deque(maxlen=KEYS_KEPT)
        self._pings: deque[float] = deque(maxlen=PINGS_KEPT)
        self._retries: set[asyncio.Task[None]] = set()

    async def send(self, key: str, text: str, *, ping: bool = False) -> Sent:
        """Send `text` now, or keep trying in the background. `ping` marks `send_to_phone`."""
        if key in self._keys:
            return "duplicate"
        if not self._link.state().paired:
            return "unpaired"
        self._keys.append(key)
        if ping:
            self._pings.append(self._clock())
        body = clip(text.strip(), REPLY_ROOM)
        if await self._try(key, body):
            return "sent"
        task = asyncio.create_task(self._retry(key, body), name=f"phone-retry-{key}")
        self._retries.add(task)
        task.add_done_callback(self._retries.discard)
        return "retrying"

    def pinged_since(self, ts: float) -> bool:
        """True when `send_to_phone` messaged the phone at `ts` or later."""
        return any(p >= ts for p in self._pings)

    async def close(self) -> None:
        tasks = list(self._retries)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _try(self, key: str, body: str) -> bool:
        state = self._link.state()
        try:
            await self._link.transport.send(state.chat_id, body)
        except Unreachable as exc:
            log.info("phone message %s not sent yet: %s", key, exc)
            return False
        return True

    async def _retry(self, key: str, body: str) -> None:
        for wait in self.retry_s:
            await asyncio.sleep(wait)
            if not self._link.state().paired:
                return
            if await self._try(key, body):
                return
        tries = len(self.retry_s) + 1
        log.warning("phone message %s dropped after %d tries", key, tries)
        self._link.host.bus.publish(
            Notice(level="warn", text=f"{DROPPED} after {tries} tries, so it was dropped: “{clip(body, 80)}”")
        )
