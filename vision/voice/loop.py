"""The voice loop: microphone audio to `user.utterance`, with the echo guard.

`Ears` (`ears.py`) opens and closes the microphone stream as the listening
mode asks and hands its audio over chunk by chunk (`hear`), with `flush` when
a stream ends. Which utterances count is `Addressing`'s decision, by the mode
(`set_mode`): only while push to talk is held (`hold`), for the name
(`wake`), or everything worth a turn (`always`).

States, as the window sees them: `idle` -> `listening` (speech started) ->
`transcribing` (speech ended) -> the session's `thinking` when the utterance
is for the assistant, or back to `idle` when it is dropped. The voice loop
publishes those three only while the session itself is idle, so it never
paints over the session's `thinking` or `speaking`.

While the assistant is speaking (an utterance that starts while the session
is `speaking`, or while a sentence is still playing), the microphone is only
checked for the stop phrases and, in `wake` and `always`, for the name. The
words that repeat the sentences being spoken are removed first, so the
assistant cannot stop itself or answer itself, even when it says its own
name. A stop phrase, or push to talk pressed while the assistant is busy,
publishes `input.interrupt`. An utterance that starts with the name and says
something after it (`barge_in`) is published as the next message; the session
stops the reply for it. Holding push to talk always makes the utterance
count, even mid-reply.

The follow-up window opens each time the session returns to `idle` after a
turn. A short chime plays each time the session starts thinking.

While a gate request waits for the user's yes or no, whatever the user says
(once the assistant's audio has stopped) is passed on without a wake phrase
(in `hold`, only what is said while push to talk is held),
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
from vision.core.events import ListenMode
from vision.voice.settings import VoiceSettings
from vision.voice.stt import Transcriber
from vision.voice.tts import Run, TtsSpeaker
from vision.voice.vad import Segmenter, SpeechDetector, SpeechStarted, Utterance
from vision.voice.wake import FILLERS, Addressing, StopMatcher, WakeMatcher, residual, words

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
        detector: SpeechDetector,
        transcriber: Transcriber,
        speaker: TtsSpeaker,
        run: Run[Any],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.bus = bus
        self.detector = detector
        self.transcriber = transcriber
        self.speaker = speaker
        self._run = run
        self._clock = clock
        wake = WakeMatcher(settings.name)
        self.addressing = Addressing(wake, settings.followup_s, settings.listen)
        self.stops = StopMatcher(wake, settings.stop_phrases)
        self.segmenter = Segmenter(silence_ms=settings.silence_ms, max_s=settings.max_utterance_s)
        self.session_state: State = "idle"
        self._shown: State = "idle"
        self._started_at = 0.0
        self._voiced_s = 0.0
        self._while_speaking = False
        self._tasks: set[asyncio.Task[None]] = set()
        self._gate_waiting: set[str] = set()
        self.on_ptt: Callable[[bool], None] = lambda down: None
        """Hears push to talk after the loop has; `Ears` opens and closes the microphone on it."""
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
                self.on_ptt(down)
            case GateRequest(id=request_id):
                self._gate_waiting.add(request_id)
            case GateResolved(id=request_id):
                self._gate_waiting.discard(request_id)

    # ------------------------------------------------------------ audio

    @property
    def mode(self) -> ListenMode:
        return self.addressing.mode

    def set_mode(self, mode: ListenMode) -> None:
        """Takes effect from the next decision, the utterance in progress included."""
        self.addressing.mode = mode

    async def hear(self, chunk: np.ndarray) -> None:
        """One chunk of microphone audio, through VAD and, at an utterance's end, recognition."""
        prob = await self._run(lambda: self.detector.probability(chunk))
        for event in self.segmenter.push(chunk, prob):
            await self.on_segment(event)

    async def flush(self) -> None:
        """The stream ended: the utterance in progress ends with it, and the next stream starts afresh."""
        for event in self.segmenter.flush():
            await self.on_segment(event)
        await self._run(self.detector.reset)

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
        self._voiced_s = event.voiced_s
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
                elif (said := self.barge_in(text, rest)) is not None:
                    self.bus.publish(UserUtterance(text=said, source="voice"))
                self._show("idle")
                return
            text = " ".join(rest)
        accepted = self.addressing.decide(text, started, now, self._voiced_s)
        if accepted is None and self._gate_waiting and self.mode != "hold":
            accepted = text.strip() or None
        if accepted is None:
            self._show("idle")
            return
        self._shown = "idle"
        self.bus.publish(UserUtterance(text=accepted, source="voice"))

    def barge_in(self, text: str, rest: list[str]) -> str | None:
        """What to send when the owner says the name over the reply, or None.

        Only in `wake` and `always`, and only from `rest`, the words left once
        the assistant's own speech is removed: its echo saying its name never
        counts. The name must be followed by words that are not fillers, so a
        stray name is not a message. The transcript's own words are kept when
        nothing in it was echo.
        """
        if self.mode == "hold":
            return None
        after = self.addressing.wake.strip(" ".join(rest))
        if after is None or not [w for w in words(after) if w not in FILLERS]:
            return None
        whole = self.addressing.wake.strip(text) if len(rest) == len(words(text)) else None
        return whole or after

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
