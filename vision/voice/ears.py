"""The microphone stream, opened and closed as the listening mode asks.

The stream is wanted while the mode listens (`wake`, `always`) or push to talk
is held; in `hold` nothing else opens it, so between presses there is no input
stream at all and macOS shows no microphone indicator. The models stay loaded
either way, so a press only waits for the device.

A press in `hold` opens the stream at once. `mic` is `opening` until the
device delivers its first sound (`Microphone.open` waits for it; AirPods take
about half a second) and `open` from then on. After the release the stream
keeps running for `TAIL_S`, so the last word is not cut, then closes. A
release that came while the device was still opening counts its tail from the
release, so a slow device does not stretch it. A stream that cannot open is
said once, as a notice, and the mode stays as it is: the next press tries
again, and only a different problem is said again.

Before a reply is spoken in `hold`, `quiet()` makes sure the stream has
closed, and with a Bluetooth headset that is both microphone and speakers
waits `settle_s` after it: such a headset plays in its low-quality call
profile while its microphone is open, and switching back takes a moment.

One task feeds the voice loop: every stream's chunks go through one queue,
with an end marker when a stream ends, so a press that opens a new stream
while the last utterance is still being transcribed never mixes the two.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable

import numpy as np

from vision.core.events import ListenMode, MicState
from vision.voice.audio_io import AudioSource
from vision.voice.loop import VoiceLoop

log = logging.getLogger(__name__)

TAIL_S = 0.4
"""After push to talk is let go, the stream keeps capturing this long."""
QUIET_WAIT_S = 1.5
"""How long a reply waits at most for a push-to-talk stream to close."""

Sleep = Callable[[float], Awaitable[None]]


class Ears:
    def __init__(
        self,
        source: AudioSource,
        loop: VoiceLoop,
        *,
        on_mic: Callable[[MicState], None],
        on_problem: Callable[[str], None],
        clock: Callable[[], float] = time.monotonic,
        sleep: Sleep = asyncio.sleep,
        tail_s: float = TAIL_S,
        settle_s: float = 0.0,
    ) -> None:
        self.source = source
        self.loop = loop
        self.mic: MicState = "closed"
        self.problem: str | None = None
        """Why the stream last failed to open, until it opens again."""
        self._on_mic = on_mic
        self._on_problem = on_problem
        self._clock = clock
        self._sleep = sleep
        self._tail_s = tail_s
        self.settle_s = settle_s
        """After the stream closes, how long a headset needs before it plays well again."""
        self._closed_at = float("-inf")
        self._closed = asyncio.Event()
        self._closed.set()
        self._held = False
        self._released_at = float("-inf")
        self._feed: asyncio.Queue[np.ndarray | None] = asyncio.Queue()
        self._said: str | None = None
        self._follow: asyncio.Task[None] | None = None
        self._pump: asyncio.Task[None] | None = None
        self._consumer: asyncio.Task[None] | None = None

    @property
    def mode(self) -> ListenMode:
        return self.loop.mode

    def wanted(self) -> bool:
        """Whether a stream should be open now: the mode listens, or push to talk is held."""
        return self.mode != "hold" or self._held

    async def start(self) -> None:
        """Start feeding the loop; in a listening mode open the stream, raising when it cannot."""
        self._consumer = asyncio.create_task(self._consume(), name="voice-ears")
        if self.wanted():
            await self._open()

    def ptt(self, down: bool) -> None:
        """Push to talk pressed or let go."""
        if self._held and not down:
            self._released_at = self._clock()
        self._held = down
        self._settle()

    def set_mode(self, mode: ListenMode) -> None:
        """A new listening mode: the stream opens or closes to match, at once."""
        self.loop.set_mode(mode)
        self._settle()

    async def quiet(self) -> None:
        """In `hold`, before a reply: the stream closed (and the headset settled), unless held."""
        if self.mode != "hold" or self._held:
            return
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._closed.wait(), QUIET_WAIT_S)
        wait = self._closed_at + self.settle_s - self._clock()
        if self.mic == "closed" and wait > 0:
            await self._sleep(wait)

    async def stop(self) -> None:
        tasks = [t for t in (self._follow, self._pump, self._consumer) if t is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._follow = self._pump = self._consumer = None
        await self.source.close()
        self._show("closed")

    # ------------------------------------------------------------ the stream

    def _settle(self) -> None:
        if self._consumer is None:
            return  # not started, or stopped
        if self._follow is None or self._follow.done():
            self._follow = asyncio.create_task(self._match(), name="voice-ears-follow")

    async def _match(self) -> None:
        """Open or close the stream until it is as wanted; one change at a time."""
        while True:
            if self.wanted() and self.mic == "closed":
                if not await self._try_open():
                    return
            elif not self.wanted() and self.mic == "open":
                wait = self._released_at + self._tail_s - self._clock()
                if wait > 0:
                    await self._sleep(wait)
                    continue
                await self._close()
            else:
                return

    async def _try_open(self) -> bool:
        try:
            await self._open()
        except Exception as exc:
            problem = str(exc) or type(exc).__name__
            log.warning("the microphone did not open: %s", problem)
            self.problem = problem
            if problem != self._said:
                self._said = problem
                self._on_problem(problem)
            return False
        return True

    async def _open(self) -> None:
        if self._pump is not None:
            await self._pump  # the last stream's chunks are all in the feed
        self._show("opening")
        try:
            await self.source.open()
        except BaseException:
            self._show("closed")
            raise
        self.problem = self._said = None
        self._show("open")
        self._pump = asyncio.create_task(self._carry(), name="voice-ears-pump")

    async def _close(self) -> None:
        await self.source.close()
        self._show("closed")

    async def _carry(self) -> None:
        """The open stream's chunks into the feed, and its end."""
        try:
            async for chunk in self.source.chunks():
                self._feed.put_nowait(chunk)
        except Exception:
            log.exception("the microphone stream failed")
            with contextlib.suppress(Exception):
                await self.source.close()
        finally:
            self._feed.put_nowait(None)
            self._show("closed")

    async def _consume(self) -> None:
        while True:
            chunk = await self._feed.get()
            try:
                if chunk is None:
                    await self.loop.flush()
                else:
                    await self.loop.hear(chunk)
            except Exception:
                log.exception("the voice loop failed on the microphone's audio")

    def _show(self, mic: MicState) -> None:
        if mic != self.mic:
            self.mic = mic
            if mic == "closed":
                self._closed_at = self._clock()
                self._closed.set()
            else:
                self._closed.clear()
            self._on_mic(mic)
