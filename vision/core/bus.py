"""In-process async publish/subscribe for Vision events.

Everything inside the daemon talks through one `Bus`. The WebSocket is a
filtered view of it.

    sub = bus.subscribe({"input.text", "input.interrupt"})   # registered now
    async with sub:
        async for event in sub:
            ...

`publish` is synchronous and never blocks: it puts the event on each matching
subscriber's queue. It must be called from the event-loop thread. From another
thread (an audio callback, say) use `loop.call_soon_threadsafe(bus.publish, ev)`.

Each subscription has a bounded queue. When a slow subscriber's queue is full
the oldest event is dropped so the publisher is never held up; this only
matters for high-rate events such as `voice.level`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Iterable
from types import TracebackType

from vision.core.events import Event

log = logging.getLogger(__name__)

DEFAULT_QUEUE_SIZE = 1000


class Subscription(AsyncIterator[Event]):
    """A live subscription. Iterate it for events; close it when done."""

    def __init__(self, bus: Bus, types: frozenset[str] | None, maxsize: int) -> None:
        self._bus = bus
        self.types = types
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize)
        self.dropped = 0

    def wants(self, event: Event) -> bool:
        return self.types is None or event.TYPE in self.types

    def _offer(self, event: Event) -> None:
        if self._queue.full():
            self._queue.get_nowait()
            self.dropped += 1
            if self.dropped == 1 or self.dropped % 100 == 0:
                log.warning("subscriber %s is slow, dropped %d events", self.types, self.dropped)
        self._queue.put_nowait(event)

    async def get(self) -> Event:
        return await self._queue.get()

    def __aiter__(self) -> Subscription:
        return self

    async def __anext__(self) -> Event:
        return await self._queue.get()

    def close(self) -> None:
        self._bus._remove(self)

    async def __aenter__(self) -> Subscription:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


class Bus:
    """The daemon's event bus."""

    def __init__(self) -> None:
        self._subs: list[Subscription] = []

    def publish(self, event: Event) -> None:
        for sub in tuple(self._subs):
            if sub.wants(event):
                sub._offer(event)

    def subscribe(
        self, types: Iterable[str] | None = None, *, maxsize: int = DEFAULT_QUEUE_SIZE
    ) -> Subscription:
        """Subscribe to the given event types, or to everything when `types` is None.

        The subscription is registered immediately, so no event published after
        this call returns is missed.
        """
        sub = Subscription(self, frozenset(types) if types is not None else None, maxsize)
        self._subs.append(sub)
        return sub

    def _remove(self, sub: Subscription) -> None:
        if sub in self._subs:
            self._subs.remove(sub)
