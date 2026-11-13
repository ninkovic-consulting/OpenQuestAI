"""Opt-in tests with the real models: `VISION_VOICE_MODELS=1 uv run pytest -s tests/test_voice_models.py`.

They load Silero VAD, Whisper and Kokoro from the disk only, so download the
speech models first (Settings, Voice, or `vision setup`), and print load,
recognition and synthesis times. No audio hardware is used.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest
import soundfile

from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.events import InputInterrupt, UserUtterance
from vision.core.session import Session
from vision.testing.fakes import FakeBrain, FakeMemory, FakeToolHost
from vision.voice.filemode import make_file_voice, resample
from vision.voice.settings import VoiceSettings
from vision.voice.stt import WhisperStt
from vision.voice.tts import KokoroSynth, SaySynth
from vision.voice.vad import FRAME, SAMPLE_RATE, Segmenter, SileroVad, Utterance
from vision.voice.wake import WakeMatcher, words

pytestmark = pytest.mark.skipif(
    os.environ.get("VISION_VOICE_MODELS") != "1",
    reason="needs model weights; set VISION_VOICE_MODELS=1",
)

USER_VOICE = "am_michael"


def timed(label: str, fn):  # type: ignore[no-untyped-def]
    started = time.perf_counter()
    result = fn()
    print(f"\n[voice] {label}: {time.perf_counter() - started:.2f} s")
    return result


@pytest.fixture(scope="module")
def models() -> Iterator[tuple[SileroVad, WhisperStt, KokoroSynth]]:
    s = VoiceSettings(name="Vision")
    vad, stt = SileroVad(s.vad_model), WhisperStt(s.stt_model)
    tts = KokoroSynth(s.tts_model, USER_VOICE)
    timed(f"load {s.vad_model}", vad.load)
    timed(f"load {s.stt_model} (with warm-up)", stt.load)
    timed(f"load {s.tts_model} (with warm-up)", tts.load)
    yield vad, stt, tts


def speak(tts: KokoroSynth, text: str) -> np.ndarray:
    audio = timed(f"synthesise {text!r}", lambda: tts.synth(text))
    print(f"[voice]   audio length {len(audio) / tts.sample_rate:.2f} s")
    return resample(audio, tts.sample_rate, SAMPLE_RATE)


def segment(vad: SileroVad, audio: np.ndarray) -> list[Utterance]:
    vad.reset()
    seg = Segmenter()
    padded = np.concatenate([audio, np.zeros(SAMPLE_RATE, dtype=np.float32)])
    out: list[Utterance] = []
    for start in range(0, len(padded) - FRAME + 1, FRAME):
        frame = padded[start : start + FRAME]
        out += [e for e in seg.push(frame, vad.probability(frame)) if isinstance(e, Utterance)]
    return out


def test_tts_wav_through_vad_and_stt(models, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    vad, stt, tts = models
    sentence = "Hey Vision, what is the weather like in Paris today?"
    wav = tmp_path / "sentence.wav"
    soundfile.write(wav, speak(tts, sentence), SAMPLE_RATE)
    audio, _ = soundfile.read(wav, dtype="float32")

    utterances = timed("VAD over the clip", lambda: segment(vad, audio))
    assert len(utterances) == 1 and utterances[0].audio.size > 0

    text = timed("transcribe one sentence", lambda: stt.transcribe(utterances[0].audio))
    print(f"[voice]   heard {text!r}")
    rest = WakeMatcher("Vision").strip(text)
    assert rest is not None
    assert {"weather", "paris", "today"} <= set(words(rest))


def test_say_fallback_synthesises() -> None:
    say = SaySynth()
    timed("load macOS say", say.load)
    audio = timed("say one sentence", lambda: say.synth("The front door is locked."))
    assert len(audio) > 0.5 * say.sample_rate and np.abs(audio).max() > 0.05


async def test_file_mode_with_the_fake_brain(models, config: Config, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    _, _, tts = models
    quiet = lambda s: np.zeros(int(s * SAMPLE_RATE), dtype=np.float32)  # noqa: E731
    clip = np.concatenate(
        [quiet(0.5), speak(tts, "Hey Vision, tell me a story."), quiet(4.0), speak(tts, "Stop."), quiet(5.0)]
    )
    soundfile.write(tmp_path / "in.wav", clip, SAMPLE_RATE)

    bus = Bus()
    sub = bus.subscribe({UserUtterance.TYPE, InputInterrupt.TYPE})
    voice = make_file_voice(config, bus, tmp_path / "in.wav", tmp_path / "out.wav")
    reply = " ".join(f"This is sentence number {n} of a long story." for n in range(1, 11))
    session = Session(bus, FakeBrain([reply], delay=0.005), voice.speaker, FakeMemory(), FakeToolHost())
    running = asyncio.create_task(session.run())
    started = time.perf_counter()
    await voice.start()
    print(f"\n[voice] file-mode start (all three models): {time.perf_counter() - started:.2f} s")
    try:
        await asyncio.wait_for(voice.source.ended.wait(), 60)
        await session.wait_idle()
    finally:
        await voice.stop()
        running.cancel()
        await asyncio.gather(running, return_exceptions=True)

    events = []
    while not sub._queue.empty():
        events.append(sub._queue.get_nowait())
    said = [e.text for e in events if isinstance(e, UserUtterance)]
    print(f"[voice]   utterances {said}")
    assert len(said) == 1 and "story" in words(said[0])
    assert any(isinstance(e, InputInterrupt) for e in events)
    out, rate = soundfile.read(tmp_path / "out.wav")
    spoken = np.count_nonzero(np.abs(out) > 0.01) / rate
    print(f"[voice]   spoke {spoken:.1f} s before the stop")
    assert 0.5 < spoken < 15
