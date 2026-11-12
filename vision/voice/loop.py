"""The voice loop: microphone to `user.utterance`, with the echo guard.

States, as the window sees them: `idle` -> `listening` (speech started) ->
`transcribing` (speech ended) -> the session's `thinking` when the utterance
is for the assistant, or back to `idle` when it is dropped. The voice loop
publishes those three only while the session itself is idle, so it never
paints over the session's `thinking` or `speaking`.

While the assistant is speaking (an utterance that starts while the session
is `speaking`, or while a sentence is still playing), the microphone is only
checked for the stop phrases. The words that repeat the sentences being
spoken are removed first, so the assistant cannot stop itself or answer
itself. A stop phrase, or push to talk pressed while the assistant is busy,
publishes `input.interrupt`. Holding push to talk always makes the utterance
count, even mid-reply.

The follow-up window opens each time the session returns to `idle` after a
turn. A short chime plays each time the session starts thinking.

While a gate request waits for the user's yes or no, whatever the user says
(once the assistant's audio has stopped) is passed on without a wake phrase,
so the session can offer it to the gate. The session stays `thinking` or
`speaking` during that wait, which would otherwise drop the answer.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from typing import Any

import numpy as np

from vision.core.bus import Bus
from vision.core.events import (
    GateRequest,
    GateResolved,
    InputInterrupt,
    InputPtt,
    State,
    StateChanged,
    UserUtterance,
)
from vision.voice.audio_io import AudioSource
from vision.voice.settings import VoiceSettings
from vision.voice.stt import Transcriber
from vision.voice.tts import Run, TtsSpeaker
from vision.voice.vad import Segmenter, SpeechDetector, SpeechStarted, Utterance
from vision.voice.wake import Addressing, StopMatcher, WakeMatcher, residual

log = logging.getLogger(__name__)

ECHO_TAIL_S = 0.5
"""After a sentence ends, the room still carries it for about this long."""
ECHO_LOOKBACK_S = 1.0
"""Sentences that ended this long before an utterance began may still be in it."""


class VoiceLoop:
    def __init__(
        self,
        bus: Bus,
        settings: VoiceSettings,
        source: AudioSource,
        detector: SpeechDetector,
        transcriber: Transcriber,
        speaker: TtsSpeaker,
        run: Run[Any],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.bus = bus
        self.source = source
        self.detector = detector
        self.transcriber = transcriber
        self.speaker = speaker
        self._run = run
        self._clock = clock
        wake = WakeMatcher(settings.name)
        self.addressing = Addressing(wake, settings.followup_s)
        self.stops = StopMatcher(wake, settings.stop_phrases)
        self.segmenter = Segmenter(silence_ms=settings.silence_ms, max_s=settings.max_utterance_s)
        self.session_state: State = "idle"
        self._shown: State = "idle"
        self._started_at = 0.0
        self._while_speaking = False
        self._tasks: set[asyncio.Task[None]] = set()
        self._gate_waiting: set[str] = set()
        self._sub = bus.subscribe(
            {StateChanged.TYPE, InputPtt.TYPE, GateRequest.TYPE, GateResolved.TYPE}
        )

    # ------------------------------------------------------------ bus events

    async def watch(self) -> None:
        """Follow the session's state and push to talk. Run as a task."""
        async with self._sub as sub:
            async for event in sub:
                self.on_event(event)

    def on_event(self, event: Any) -> None:
        now = self._clock()
        match event:
            case StateChanged(state=state, brain=brain) if brain is not None:
                if state == "idle" and self.session_state != "idle":
                    self.addressing.open_window(now)
                if state == "thinking" and self.session_state != "thinking":
                    self._spawn(self.speaker.chime())
                self.session_state = state
                self._shown = "idle"
            case InputPtt(down=down):
                self.addressing.ptt(down, now)
                if down and self.session_state != "idle":
                    self.bus.publish(InputInterrupt())
            case GateRequest(id=request_id):
                self._gate_waiting.add(request_id)
            case GateResolved(id=request_id):
                self._gate_waiting.discard(request_id)

    # ------------------------------------------------------------ audio

    async def listen(self) -> None:
        """Run the microphone through VAD and recognition until the source ends."""
        async for chunk in self.source.chunks():
            prob = await self._run(lambda: self.detector.probability(chunk))
            for event in self.segmenter.push(chunk, prob):
                await self.on_segment(event)
        for event in self.segmenter.flush():
            await self.on_segment(event)

    def assistant_speaking(self, now: float) -> bool:
        """Audio is playing (or just ended), or a reply is being spoken.

        While a gate request waits, only the audio counts: the session stays
        `speaking` after a sentence said before the tool call.
        """
        audio = self.speaker.playing or now - self.speaker.last_end < ECHO_TAIL_S
        return audio or (self.session_state == "speaking" and not self._gate_waiting)

    async def on_segment(self, event: SpeechStarted | Utterance) -> None:
        if isinstance(event, SpeechStarted):
            self._started_at = self._clock()
            self._while_speaking = self.assistant_speaking(self._started_at)
            self._show("listening")
            return
        if event.audio.size == 0:
            self._show("idle")
            return
        self._show("transcribing")
        audio: np.ndarray = event.audio
        text = await self._run(lambda: self.transcriber.transcribe(audio))
        log.debug("heard %r", text)
        self.handle(text)

    def handle(self, text: str) -> None:
        """Act on one transcript; the utterance started at `self._started_at`."""
        now = self._clock()
        started = self._started_at
        if self._while_speaking or self.assistant_speaking(now):
            rest = residual(text, self.speaker.spoken_since(started - ECHO_LOOKBACK_S))
            if not self.addressing.held_during(started):
                if self.stops.matches(rest):
                    self.bus.publish(InputInterrupt())
                self._show("idle")
                return
            text = " ".join(rest)
        accepted = self.addressing.decide(text, started, now)
        if accepted is None and self._gate_waiting:
            accepted = text.strip() or None
        if accepted is None:
            self._show("idle")
            return
        self._shown = "idle"
        self.bus.publish(UserUtterance(text=accepted, source="voice"))

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _show(self, state: State) -> None:
        """Publish the voice's own state, only over an idle session and only on change."""
        if self.session_state != "idle" or self._while_speaking or state == self._shown:
            return
        self._shown = state
        self.bus.publish(StateChanged(state=state))
