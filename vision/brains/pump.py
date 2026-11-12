"""Runs a brain's producer in its own task so `interrupt()` can stop it at once.

A producer is a coroutine that calls `emit(event)` for each `BrainEvent` it
makes. `Pump.run` yields those events in order. `stop()` ends the iteration
immediately and cancels the producer, which closes its network stream. An
exception raised by the producer is re-raised from `run`.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import cast

from vision.core.interfaces import BrainEvent

Emit = Callable[[BrainEvent], None]
Producer = Callable[[Emit], Awaitable[None]]

_END = object()


class Pump:
    def __init__(self) -> None:
        self._stop = asyncio.Event()
        self.interrupted = False

    def stop(self) -> None:
        self._stop.set()

    async def run(self, producer: Producer) -> AsyncIterator[BrainEvent]:
        self._stop = asyncio.Event()
        self.interrupted = False
        queue: asyncio.Queue[object] = asyncio.Queue()

        async def main() -> None:
            try:
                await producer(queue.put_nowait)
            finally:
                queue.put_nowait(_END)

        task = asyncio.create_task(main())
        stopped = asyncio.create_task(self._stop.wait())
        try:
            while True:
                if self._stop.is_set():
                    self.interrupted = True
                    return
                getter = asyncio.create_task(queue.get())
                await asyncio.wait({getter, stopped}, return_when=asyncio.FIRST_COMPLETED)
                if not getter.done():
                    getter.cancel()
                    self.interrupted = True
                    return
                item = getter.result()
                if item is _END:
                    break
                yield cast(BrainEvent, item)
            await task
        finally:
            stopped.cancel()
            task.cancel()
            await asyncio.gather(task, stopped, return_exceptions=True)
