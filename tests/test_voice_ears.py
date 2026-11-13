"""The microphone stream by listening mode: none between presses in `hold`, open in `wake` and `always`.

No hardware: the microphone is a fake whose first audio arrives when the test
says, the clock is a fake, VAD is loudness and transcripts are scripted.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import numpy as np
import pytest

from tests.test_voice_fakes import LoudnessVad, ScriptedStt, ToneSynth, drain, run_now
from vision.core.bus import Bus
from vision.core.events import InputPtt, ListenMode, MicState, Notice, UserUtterance
from vision.voice.ears import TAIL_S, Ears
from vision.voice.errors import VoiceUnavailable
from vision.voice.filemode import WavSink
from vision.voice.loop import VoiceLoop
from vision.voice.settings import VoiceSettings
from vision.voice.tts import TtsSpeaker
from vision.voice.vad import FRAME, SAMPLE_RATE

LOUD = np.full(FRAME, 0.5, dtype=np.float32)
QUIET = np.zeros(FRAME, dtype=np.float32)


class FakeMic:
    """A microphone stream: `open` waits until `arrive()` (the device's first audio), unless `fail` is set."""

    def __init__(self) -> None:
        self.opens = 0
        self.closes = 0
        self.fail: str | None = None
        self.slow = False
        self._arrived = asyncio.Event()
        self._queue: asyncio.Queue[np.ndarray | None] = asyncio.Queue()
        self.is_open = False

    def arrive(self) -> None:
        self._arrived.set()

    async def open(self) -> None:
        self.opens += 1
        if self.fail is not None:
            raise VoiceUnavailable(self.fail)
        if self.slow:
            await self._arrived.wait()
        self._queue = asyncio.Queue()
        self.is_open = True

    def chunks(self) -> AsyncIterator[np.ndarray]:
        return self._drain(self._queue)

    async def _drain(self, queue: asyncio.Queue[np.ndarray | None]) -> AsyncIterator[np.ndarray]:
        while (chunk := await queue.get()) is not None:
            yield chunk

    async def close(self) -> None:
        if self.is_open:
            self.closes += 1
            self.is_open = False
            self._queue.put_nowait(None)

    def say(self, *frames: np.ndarray) -> None:
        assert self.is_open, "audio from a closed microphone"
        for frame in frames:
            self._queue.put_nowait(frame)


class Clock:
    def __init__(self) -> None:
        self.now = 100.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds
        await asyncio.sleep(0)


class Rig:
    def __init__(self, tmp_path: Path, *transcripts: str, listen: ListenMode = "hold") -> None:
        self.bus = Bus()
        self.sub = self.bus.subscribe({UserUtterance.TYPE, Notice.TYPE})
        self.clock = Clock()
        self.mic = FakeMic()
        self.stt = ScriptedStt(*transcripts)
        sink = WavSink(tmp_path / "out.wav")
        sink.open()
        speaker = TtsSpeaker(self.bus, sink, run_now)
        speaker.use(ToneSynth(0.1))
        self.loop = VoiceLoop(
            self.bus, VoiceSettings(name="Vision", listen=listen), LoudnessVad(), self.stt, speaker, run_now, self.clock
        )
        self.states: list[MicState] = []
        self.problems: list[str] = []
        self.ears = Ears(
            self.mic,
            self.loop,
            on_mic=self.states.append,
            on_problem=self.problems.append,
            clock=self.clock,
            sleep=self.clock.sleep,
        )
        self.loop.on_ptt = self.ears.ptt

    def press(self, down: bool) -> None:
        self.loop.on_event(InputPtt(down=down))

    async def settle(self) -> None:
        for _ in range(50):
            await asyncio.sleep(0)

    async def heard(self) -> list[str]:
        await self.settle()
        return [e.text for e in await drain(self.sub) if isinstance(e, UserUtterance)]


def speech(frames: int) -> list[np.ndarray]:
    return [LOUD] * frames


# ---------------------------------------------------------------- hold


async def test_hold_has_no_stream_before_a_press(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    await rig.ears.start()
    await rig.settle()
    assert rig.mic.opens == 0 and rig.ears.mic == "closed" and rig.states == []
    await rig.ears.stop()


async def test_a_press_opens_the_stream_and_the_release_closes_it_after_the_tail(tmp_path: Path) -> None:
    rig = Rig(tmp_path, "Lights on in the hall.")
    await rig.ears.start()
    rig.press(True)
    await rig.settle()
    assert rig.mic.opens == 1 and rig.ears.mic == "open"
    rig.mic.say(*speech(12))
    await rig.settle()
    rig.press(False)
    rig.mic.say(*speech(3))  # the last word, said as the key comes up
    await rig.settle()
    assert rig.clock.slept == [pytest.approx(TAIL_S)]
    assert rig.mic.closes == 1 and rig.ears.mic == "closed"
    assert rig.states == ["opening", "open", "closed"]
    assert await rig.heard() == ["Lights on in the hall."]
    # Every frame from the first to the tail went to recognition.
    assert rig.stt.heard == [15 * FRAME / SAMPLE_RATE]
    await rig.ears.stop()


async def test_speech_after_a_press_without_the_key_is_not_taken(tmp_path: Path) -> None:
    rig = Rig(tmp_path, "Vision, lights on.")
    await rig.ears.start()
    rig.press(True)
    await rig.settle()
    rig.press(False)
    await rig.settle()
    assert rig.mic.closes == 1
    # The stream is closed: nothing reaches the loop until the next press.
    assert not rig.mic.is_open
    await rig.ears.stop()


async def test_a_slow_device_shows_opening_until_its_first_audio(tmp_path: Path) -> None:
    rig = Rig(tmp_path, "What is on today?")
    rig.mic.slow = True
    await rig.ears.start()
    rig.press(True)
    await rig.settle()
    assert rig.ears.mic == "opening" and rig.states == ["opening"]
    rig.clock.now += 0.5  # AirPods: the first sample about half a second after opening
    rig.mic.arrive()
    await rig.settle()
    assert rig.ears.mic == "open"
    rig.mic.say(*speech(20))
    await rig.settle()
    rig.press(False)
    await rig.settle()
    assert rig.states == ["opening", "open", "closed"]
    assert rig.problems == []
    assert await rig.heard() == ["What is on today?"]
    await rig.ears.stop()


async def test_a_release_before_the_first_audio_counts_its_tail_from_the_release(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.mic.slow = True
    await rig.ears.start()
    rig.press(True)
    await rig.settle()
    rig.press(False)  # let go at once
    rig.clock.now += 0.3
    rig.mic.arrive()
    await rig.settle()
    assert rig.clock.slept == [pytest.approx(TAIL_S - 0.3)]
    assert rig.mic.closes == 1 and rig.ears.mic == "closed"
    await rig.ears.stop()


async def test_a_failed_open_is_said_once_and_hold_stays(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.mic.fail = "The microphone “Desk” could not open."
    await rig.ears.start()
    for _ in range(2):
        rig.press(True)
        await rig.settle()
        rig.press(False)
        await rig.settle()
    assert rig.mic.opens == 2
    assert rig.problems == ["The microphone “Desk” could not open."]
    assert rig.ears.mic == "closed" and rig.loop.mode == "hold"
    assert rig.ears.problem == "The microphone “Desk” could not open."
    rig.mic.fail = None
    rig.press(True)
    await rig.settle()
    assert rig.ears.mic == "open" and rig.ears.problem is None
    await rig.ears.stop()


# ---------------------------------------------------------------- wake and always


async def test_a_listening_mode_opens_at_start_and_stays_open_across_presses(tmp_path: Path) -> None:
    rig = Rig(tmp_path, listen="wake")
    await rig.ears.start()
    assert rig.mic.opens == 1 and rig.ears.mic == "open"
    rig.press(True)
    rig.press(False)
    await rig.settle()
    assert rig.mic.closes == 0 and rig.ears.mic == "open"
    await rig.ears.stop()
    assert rig.mic.closes == 1


async def test_a_listening_mode_that_cannot_open_fails_the_start(tmp_path: Path) -> None:
    rig = Rig(tmp_path, listen="always")
    rig.mic.fail = "No microphone."
    with pytest.raises(VoiceUnavailable, match="No microphone."):
        await rig.ears.start()
    await rig.ears.stop()


# ---------------------------------------------------------------- changing the mode


async def test_changing_the_mode_while_idle_opens_and_closes_the_stream(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    await rig.ears.start()
    rig.ears.set_mode("wake")
    await rig.settle()
    assert rig.ears.mic == "open" and rig.mic.opens == 1
    rig.ears.set_mode("always")
    await rig.settle()
    assert rig.mic.opens == 1  # already open
    rig.ears.set_mode("hold")
    await rig.settle()
    assert rig.ears.mic == "closed" and rig.mic.closes == 1
    assert rig.clock.slept == []  # nobody let go of a key: no tail
    await rig.ears.stop()


async def test_switching_to_hold_mid_utterance_ends_it_by_the_new_rule(tmp_path: Path) -> None:
    rig = Rig(tmp_path, "Vision, lights on.", listen="wake")
    await rig.ears.start()
    rig.mic.say(*speech(12))
    await rig.settle()
    assert rig.loop.segmenter.in_speech
    rig.ears.set_mode("hold")
    await rig.settle()
    assert rig.ears.mic == "closed"
    assert rig.stt.heard  # the utterance in progress was ended and recognised
    assert await rig.heard() == []  # but in hold only what is said while holding counts
    await rig.ears.stop()


async def test_switching_to_a_listening_mode_while_holding_keeps_the_stream_after_the_release(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    await rig.ears.start()
    rig.press(True)
    await rig.settle()
    rig.ears.set_mode("wake")
    rig.press(False)
    await rig.settle()
    assert rig.ears.mic == "open" and rig.mic.closes == 0
    await rig.ears.stop()


async def test_a_new_press_while_the_last_utterance_is_still_heard_keeps_them_apart(tmp_path: Path) -> None:
    rig = Rig(tmp_path, "First thing.", "Second thing.")
    await rig.ears.start()
    rig.press(True)
    await rig.settle()
    rig.mic.say(*speech(10))
    rig.press(False)
    rig.press(True)  # pressed again inside the tail: the same stream goes on
    await rig.settle()
    rig.mic.say(*[QUIET] * 25, *speech(10))
    await rig.settle()
    rig.press(False)
    await rig.settle()
    assert rig.mic.opens == 1
    assert await rig.heard() == ["First thing.", "Second thing."]
    await rig.ears.stop()


# ---------------------------------------------------------------- before a reply


async def test_a_reply_in_hold_waits_for_the_stream_to_close_and_a_headset_to_settle(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.ears.settle_s = 0.3
    await rig.ears.start()
    rig.press(True)
    await rig.settle()
    rig.press(False)  # the tail is still running when the reply is ready
    quiet = asyncio.create_task(rig.ears.quiet())
    await rig.settle()
    assert quiet.done() and rig.mic.closes == 1
    assert rig.clock.slept == [pytest.approx(TAIL_S), pytest.approx(0.3)]  # the tail, then the settle
    await rig.ears.stop()


async def test_a_listening_mode_does_not_wait_before_a_reply(tmp_path: Path) -> None:
    rig = Rig(tmp_path, listen="wake")
    rig.ears.settle_s = 0.3
    await rig.ears.start()
    await asyncio.wait_for(rig.ears.quiet(), 0.1)
    assert rig.ears.mic == "open" and rig.clock.slept == []
    await rig.ears.stop()
