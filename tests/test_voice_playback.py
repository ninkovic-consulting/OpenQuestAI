"""Speaking a reply: one stream, sentences back to back, the pre-buffer, a slow sentence,
an interrupt with audio buffered, underruns and gaps counted, and the Bluetooth headset.

No sound: the output device is a fake that the test (or a small driver task) pulls
samples from, the synthesiser is a fake with chosen delays, and the clock is a fake
where the timing is the point.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import subprocess
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, TypeVar

import numpy as np
import pytest

from tests.test_voice_audio_io import MAC_MIC, MAC_SPEAKERS, FakeSd
from vision.core.bus import Bus
from vision.voice import audio_io
from vision.voice.audio_io import SpeakerOutput
from vision.voice.bluetooth import BLUETOOTH, bluetooth_names, one_headset
from vision.voice.tts import TtsSpeaker

T = TypeVar("T")
RATE = 24_000
BLOCK = 480  # 20 ms at 24 kHz


@pytest.fixture
def sd(monkeypatch: pytest.MonkeyPatch) -> FakeSd:
    fake = FakeSd([MAC_MIC, MAC_SPEAKERS], [])
    monkeypatch.setattr(audio_io, "_sd", lambda: fake)
    return fake


def tone(value: float, seconds: float) -> np.ndarray:
    return np.full(int(seconds * RATE), value, dtype=np.float32)


class Device:
    """Pulls from the open output stream as fast as the loop turns, or `paced` in real time
    (20 ms per 20 ms block, as a sound card does), keeping what it played."""

    def __init__(self, sd: FakeSd, paced: bool = False) -> None:
        self.sd = sd
        self.pace = BLOCK / RATE if paced else 0.0
        self.heard: list[np.ndarray] = []
        self.blocks = 0
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self.pace)
            streams = [s for s in self.sd.streams if s.kw.get("output") and not s.closed]
            if streams:
                try:
                    self.heard.append(streams[-1].pull(BLOCK))
                    self.blocks += 1
                except self.sd.CallbackAbort:
                    streams[-1].closed = True

    def played(self) -> np.ndarray:
        """What was played, without the silence before the first sound and after the last."""
        audio = np.concatenate(self.heard) if self.heard else np.zeros(0, dtype=np.float32)
        loud = np.flatnonzero(audio)
        return audio[loud[0] : loud[-1] + 1] if loud.size else audio

    async def close(self) -> None:
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)


# ---------------------------------------------------------------- the stream


async def test_sentences_queued_in_order_play_back_to_back_on_one_stream(sd: FakeSd) -> None:
    out = SpeakerOutput(linger_s=0.05)
    device = Device(sd)
    parts = [tone(0.1, 0.3), tone(0.2, 0.25), tone(0.3, 0.4)]
    played = [asyncio.create_task(out.play(p, RATE)) for p in parts]
    assert all(await asyncio.gather(*played))
    await asyncio.sleep(0.1)
    await device.close()
    assert len([s for s in sd.streams if s.kw.get("output")]) == 1
    assert np.array_equal(device.played(), np.concatenate(parts))  # no gap, nothing twice
    assert out.gaps == 0 and out.underruns == 0
    assert sd.streams[-1].closed and not out.streaming
    assert sd.streams[-1].kw["latency"] == SpeakerOutput.LATENCY_S


async def test_a_sentence_that_comes_late_is_a_gap_and_is_logged_once(
    sd: FakeSd, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="vision.voice.audio_io")
    out = SpeakerOutput(linger_s=0.2)
    device = Device(sd)
    assert await out.play(tone(0.1, 0.1), RATE)
    for _ in range(20):  # the device asks for more and the stream runs dry
        await asyncio.sleep(0)
    assert await out.play(tone(0.2, 0.1), RATE)
    await asyncio.sleep(0.3)
    await device.close()
    assert len([s for s in sd.streams if s.kw.get("output")]) == 1
    assert out.gaps == 1
    assert [r.getMessage() for r in caplog.records] == [
        "a reply played with 0 underrun(s) and 1 gap(s) between sentences"
    ]


async def test_an_underrun_from_the_device_is_counted(sd: FakeSd) -> None:
    out = SpeakerOutput(linger_s=0.01)
    playing = asyncio.create_task(out.play(tone(0.1, 0.05), RATE))
    await asyncio.sleep(0.01)
    stream = sd.streams[-1]
    block = np.zeros((BLOCK, 1), dtype=np.float32)
    stream.kw["callback"](block, BLOCK, None, SimpleNamespace(output_underflow=True))
    while not playing.done():
        stream.pull(BLOCK)
        await asyncio.sleep(0)
    assert out.underruns == 1


async def test_stop_silences_at_once_with_audio_buffered(sd: FakeSd) -> None:
    out = SpeakerOutput()
    first = asyncio.create_task(out.play(tone(0.1, 2.0), RATE))
    second = asyncio.create_task(out.play(tone(0.2, 2.0), RATE))
    await asyncio.sleep(0.01)
    stream = sd.streams[-1]
    stream.pull(BLOCK)
    out.stop()
    assert await first is False and await second is False
    with pytest.raises(sd.CallbackAbort):  # the device's own buffer is dropped too
        stream.pull(BLOCK)
    await asyncio.sleep(0.01)
    assert stream.closed and not out.streaming
    # The next reply opens a fresh stream.
    device = Device(sd)
    assert await out.play(tone(0.3, 0.05), RATE)
    await device.close()
    assert len([s for s in sd.streams if s.kw.get("output")]) == 2


# ---------------------------------------------------------------- the speaker


class SlowSynth:
    """A tone per sentence; `slow` sentences take `delay` seconds to make."""

    sample_rate = RATE

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self.made: list[str] = []

    def load(self) -> None:
        pass

    def synth(self, text: str) -> np.ndarray:
        self.made.append(text)
        return tone(0.1 + 0.1 * len(self.made), self.seconds)


def runner(delays: dict[str, float]) -> Callable[[Callable[[], T]], Any]:
    """Like the model worker, one at a time, with a chosen delay per sentence."""
    lock = asyncio.Lock()

    async def run(fn: Callable[[], T]) -> T:
        async with lock:
            await asyncio.sleep(delays.get(getattr(fn, "text", ""), 0.0))
            return fn()

    return run


def speaker_for(sd: FakeSd, synth: SlowSynth, run: Any, linger_s: float = 0.05) -> tuple[TtsSpeaker, SpeakerOutput]:
    out = SpeakerOutput(linger_s=linger_s)
    speaker = TtsSpeaker(Bus(), out, run)
    speaker.use(synth)
    return speaker, out


async def say_in_order(speaker: TtsSpeaker, sentences: list[str], spacing: float = 0.0) -> None:
    """As the session does: each sentence handed over while the one before plays."""
    tasks = []
    for s in sentences:
        tasks.append(asyncio.create_task(speaker.say(s)))
        await asyncio.sleep(spacing)
    await asyncio.gather(*tasks)


async def test_a_reply_plays_as_one_continuous_stream(sd: FakeSd) -> None:
    synth = SlowSynth(0.2)
    speaker, out = speaker_for(sd, synth, runner({}))
    device = Device(sd, paced=True)
    await say_in_order(speaker, ["One.", "Two.", "Three."])
    await asyncio.sleep(0.1)
    await device.close()
    played = device.played()
    expected = np.concatenate([tone(0.2, 0.2), tone(0.3, 0.2), tone(0.4, 0.2)])
    assert np.array_equal(played, expected)
    assert out.gaps == 0
    assert speaker.spoken_since(0) == ["One.", "Two.", "Three."]


async def test_a_short_first_sentence_waits_for_the_next_one_being_made(sd: FakeSd) -> None:
    synth = SlowSynth(0.05)  # far shorter than the pre-buffer
    slow = {"Two.": 0.05}

    async def run(fn: Callable[[], T]) -> T:
        await asyncio.sleep(slow.pop("Two.", 0.0) if synth.made else 0.0)
        return fn()

    speaker, out = speaker_for(sd, synth, run)
    device = Device(sd, paced=True)
    await say_in_order(speaker, ["One.", "Two."])
    await asyncio.sleep(0.1)
    await device.close()
    assert out.gaps == 0  # the second was ready before the first ended
    assert np.array_equal(device.played(), np.concatenate([tone(0.2, 0.05), tone(0.3, 0.05)]))


async def test_a_slow_sentence_in_the_middle_never_cuts_one_in_half(sd: FakeSd) -> None:
    synth = SlowSynth(0.1)
    made = 0

    async def run(fn: Callable[[], T]) -> T:
        nonlocal made
        made += 1
        if made == 3:
            await asyncio.sleep(0.3)  # the third takes longer than the second plays
        return fn()

    speaker, out = speaker_for(sd, synth, run, linger_s=SpeakerOutput.LINGER_S)
    speaker.PREBUFFER_S = 0.0
    device = Device(sd, paced=True)
    await say_in_order(speaker, ["One.", "Two.", "Three."])
    await asyncio.sleep(0.1)
    await device.close()
    audio = np.concatenate(device.heard)
    # Each sentence is whole and in order; the only silence is between two of them.
    runs = [(value, len(list(group))) for value, group in itertools.groupby(np.round(audio, 3))]
    loud = [(v, n) for v, n in runs if v > 0]
    assert [v for v, _ in loud] == pytest.approx([0.2, 0.3, 0.4])
    assert [n for _, n in loud] == [int(0.1 * RATE)] * 3
    assert out.gaps == 1


async def test_stop_with_sentences_queued_drops_them_all(sd: FakeSd) -> None:
    synth = SlowSynth(1.0)
    speaker, out = speaker_for(sd, synth, runner({}))
    speaker.PREBUFFER_S = 0.0
    speaking = asyncio.create_task(say_in_order(speaker, ["One.", "Two.", "Three."]))
    await asyncio.sleep(0.05)
    assert speaker.playing
    await speaker.stop()
    await asyncio.wait_for(speaking, 1)
    assert not speaker.playing
    assert out.streaming is False or sd.streams[-1].closed


async def test_before_speaking_runs_once_per_reply(sd: FakeSd) -> None:
    synth = SlowSynth(0.05)
    speaker, _ = speaker_for(sd, synth, runner({}))
    calls = 0

    async def before() -> None:
        nonlocal calls
        calls += 1

    speaker.before_speaking = before
    device = Device(sd)
    await say_in_order(speaker, ["One.", "Two."])
    await say_in_order(speaker, ["Three."])
    await device.close()
    assert calls == 2


# ---------------------------------------------------------------- Bluetooth


def profiler(*items: dict[str, Any]) -> Callable[..., subprocess.CompletedProcess[str]]:
    def run(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        assert cmd == ["system_profiler", "SPAudioDataType", "-json"]
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"SPAudioDataType": [{"_items": list(items)}]}))

    return run


def test_bluetooth_devices_come_from_macos() -> None:
    run = profiler(
        {"_name": "Sam's AirPods Pro", "coreaudio_device_transport": BLUETOOTH},
        {"_name": "MacBook Pro Speakers", "coreaudio_device_transport": "coreaudio_device_type_builtin"},
    )
    names = bluetooth_names(run)
    assert names == {"Sam's AirPods Pro"}
    assert one_headset("Sam's AirPods Pro", "Sam's AirPods Pro", names)
    assert not one_headset("MacBook Pro Microphone", "Sam's AirPods Pro", names)
    assert not one_headset("MacBook Pro Speakers", "MacBook Pro Speakers", names)


def test_no_answer_from_macos_means_no_headset() -> None:
    def broken(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd, 5)

    assert bluetooth_names(broken) == frozenset()
