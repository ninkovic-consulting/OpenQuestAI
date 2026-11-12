"""The speaker: levels, sentence order, stop() and the WAV sink (no models, no devices)."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import numpy as np
import pytest
import soundfile

from tests.test_voice_fakes import ToneSynth, drain, run_now
from vision.core.bus import Bus
from vision.core.events import VoiceLevel
from vision.core.interfaces import Speaker
from vision.voice.filemode import WavSink
from vision.voice.tts import TtsSpeaker


@pytest.fixture
def out_wav(tmp_path: Path) -> Path:
    return tmp_path / "out.wav"


def make_speaker(bus: Bus, out_wav: Path, seconds: float = 0.3) -> tuple[TtsSpeaker, ToneSynth, WavSink]:
    synth = ToneSynth(seconds)
    sink = WavSink(out_wav)
    sink.open()
    speaker = TtsSpeaker(bus, sink, run_now)
    speaker.use(synth)
    return speaker, synth, sink


async def test_speaker_satisfies_the_protocol(out_wav: Path) -> None:
    speaker, _, _ = make_speaker(Bus(), out_wav)
    assert isinstance(speaker, Speaker)


async def test_say_publishes_levels_about_30_times_a_second(out_wav: Path) -> None:
    bus = Bus()
    sub = bus.subscribe({VoiceLevel.TYPE})
    speaker, _, _ = make_speaker(bus, out_wav, seconds=0.5)
    started = time.monotonic()
    await speaker.say("The kitchen lights are off.")
    elapsed = time.monotonic() - started
    levels = [e.level for e in await drain(sub) if isinstance(e, VoiceLevel)]
    assert 0.45 < elapsed < 0.8
    assert 10 <= len(levels) <= 20
    assert max(levels) > 0.5
    assert levels[-1] == 0.0


async def test_sentences_play_in_order_and_are_remembered(out_wav: Path) -> None:
    speaker, synth, _ = make_speaker(Bus(), out_wav, seconds=0.05)
    since = time.monotonic()
    for sentence in ["One.", "Two.", "Three."]:
        await speaker.say(sentence)
    assert synth.texts == ["One.", "Two.", "Three."]
    assert speaker.spoken_since(since) == ["One.", "Two.", "Three."]
    assert not speaker.playing
    audio, rate = soundfile.read(out_wav)
    assert rate == 24_000 and len(audio) >= 0.15 * rate


async def test_stop_cuts_a_sentence_off_within_100_ms(out_wav: Path) -> None:
    speaker, _, _ = make_speaker(Bus(), out_wav, seconds=3.0)
    task = asyncio.create_task(speaker.say("A very long sentence."))
    await asyncio.sleep(0.3)
    assert speaker.playing
    stopped = time.monotonic()
    await speaker.stop()
    await task
    assert time.monotonic() - stopped < 0.1
    audio, rate = soundfile.read(out_wav)
    assert 0.2 * rate < len(audio) < 0.5 * rate


async def test_stop_during_synthesis_drops_the_sentence(out_wav: Path) -> None:
    gate = asyncio.Event()

    async def slow_run(fn):  # type: ignore[no-untyped-def]
        await gate.wait()
        return fn()

    synth = ToneSynth()
    sink = WavSink(out_wav)
    speaker = TtsSpeaker(Bus(), sink, slow_run)
    speaker.use(synth)
    task = asyncio.create_task(speaker.say("Never heard."))
    await asyncio.sleep(0.01)
    await speaker.stop()
    gate.set()
    await task
    assert not out_wav.exists()
    assert speaker.spoken_since(0) == []
    # The next sentence still plays.
    await speaker.say("Heard.")
    assert out_wav.exists()


async def test_stop_when_silent_is_safe(out_wav: Path) -> None:
    speaker, _, _ = make_speaker(Bus(), out_wav)
    await speaker.stop()
    await speaker.say("Still works.")
    assert speaker.spoken_since(0) == ["Still works."]


async def test_empty_sentences_are_skipped(out_wav: Path) -> None:
    speaker, synth, _ = make_speaker(Bus(), out_wav)
    await speaker.say("  ...  ")
    assert synth.texts == []


async def test_say_before_start_raises(out_wav: Path) -> None:
    speaker = TtsSpeaker(Bus(), WavSink(out_wav), run_now)
    with pytest.raises(RuntimeError):
        await speaker.say("Too early.")


async def test_wav_sink_keeps_the_timeline(out_wav: Path) -> None:
    sink = WavSink(out_wav, sample_rate=8_000)
    sink.open()
    await asyncio.sleep(0.2)
    assert await sink.play(np.ones(800, dtype=np.float32), 8_000)
    audio, _ = soundfile.read(out_wav)
    first = int(np.argmax(audio > 0))
    assert 0.18 * 8_000 < first < 0.3 * 8_000
