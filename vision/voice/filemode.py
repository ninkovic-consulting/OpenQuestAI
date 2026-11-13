"""File mode: the voice pipeline fed from a WAV file, speaking into a WAV file.

No audio hardware is touched. Both ends keep the same timeline: with
`pace=1.0` the input is fed at real time and the output file holds the
assistant's speech at the moment it was said, so the two files line up.
`pace=2.0` runs twice as fast; `pace=0` feeds input as fast as the models go
(and makes speech take no time). Nobody holds push to talk to a file, so a
file is listened to for the name (`wake`) when the config says `hold`.

    voice = make_file_voice(config, bus, "in.wav", "out.wav")
    await voice.start()
    await voice.source.ended.wait()
"""

from __future__ import annotations

import asyncio
import dataclasses
import time
from collections.abc import AsyncIterator
from math import gcd
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

from vision.core.bus import Bus
from vision.core.config import Config
from vision.voice.service import LocalVoice, default_models
from vision.voice.settings import VoiceSettings
from vision.voice.vad import FRAME, SAMPLE_RATE


def resample(audio: np.ndarray, rate: int, target: int) -> np.ndarray:
    if rate == target:
        return audio.astype(np.float32, copy=False)
    g = gcd(rate, target)
    return resample_poly(audio, target // g, rate // g).astype(np.float32)


class FileSource:
    """Reads a WAV file and yields it as 16 kHz chunks, then `tail_s` of silence."""

    def __init__(self, path: str | Path, *, pace: float = 1.0, tail_s: float = 1.5) -> None:
        self.path = Path(path)
        self.pace = pace
        self.tail_s = tail_s
        self.ended = asyncio.Event()
        self._audio = np.zeros(0, dtype=np.float32)
        self._closed = False

    async def open(self) -> None:
        import soundfile

        audio, rate = soundfile.read(self.path, dtype="float32", always_2d=True)
        mono = resample(audio.mean(axis=1), rate, SAMPLE_RATE)
        tail = np.zeros(int(self.tail_s * SAMPLE_RATE), dtype=np.float32)
        self._audio = np.concatenate([mono, tail])

    async def chunks(self) -> AsyncIterator[np.ndarray]:
        t0 = time.monotonic()
        step = FRAME / SAMPLE_RATE / self.pace if self.pace > 0 else 0.0
        for i, start in enumerate(range(0, len(self._audio) - FRAME + 1, FRAME)):
            if self._closed:
                break
            if step:
                await asyncio.sleep(max(0.0, t0 + i * step - time.monotonic()))
            yield self._audio[start : start + FRAME]
        self.ended.set()

    async def close(self) -> None:
        self._closed = True


class WavSink:
    """Writes what the assistant says into a WAV file, on the input's timeline."""

    def __init__(self, path: str | Path, *, pace: float = 1.0, sample_rate: int = 24_000) -> None:
        self.path = Path(path)
        self.pace = pace
        self.sample_rate = sample_rate
        self._t0 = time.monotonic()
        self._segments: list[tuple[int, np.ndarray]] = []
        self._stop = asyncio.Event()
        self._started: float | None = None
        self._duration = 0.0
        self._turn = asyncio.Lock()
        self._stops = 0

    def open(self) -> None:
        self._t0 = time.monotonic()

    def stop(self) -> None:
        self._stops += 1  # what waits in line is dropped too
        self._stop.set()

    def position(self) -> float:
        if self._started is None:
            return 0.0
        if self.pace <= 0:
            return self._duration
        return min((time.monotonic() - self._started) * self.pace, self._duration)

    async def play(self, audio: np.ndarray, sample_rate: int) -> bool:
        """One after another, in call order, as the speakers play a reply."""
        stops = self._stops
        async with self._turn:
            return stops == self._stops and await self._play(audio, sample_rate)

    async def _play(self, audio: np.ndarray, sample_rate: int) -> bool:
        stop = self._stop = asyncio.Event()
        audio = resample(audio, sample_rate, self.sample_rate)
        self._started = time.monotonic()
        self._duration = len(audio) / self.sample_rate
        offset = int((self._started - self._t0) * max(self.pace, 0.0) * self.sample_rate)
        finished = True
        if self.pace > 0:
            try:
                await asyncio.wait_for(stop.wait(), self._duration / self.pace)
                finished = False
            except TimeoutError:
                pass
        played = audio if finished else audio[: int(self.position() * self.sample_rate)]
        self._started = None
        self._segments.append((offset, played))
        self._write()
        return finished

    def _write(self) -> None:
        import soundfile

        end = max(offset + len(seg) for offset, seg in self._segments)
        out = np.zeros(end, dtype=np.float32)
        for offset, seg in self._segments:
            out[offset : offset + len(seg)] += seg
        soundfile.write(self.path, out, self.sample_rate)


def make_file_voice(
    config: Config, bus: Bus, input_wav: str | Path, output_wav: str | Path, *, pace: float = 1.0
) -> LocalVoice:
    """The real pipeline and models, with files in place of the microphone and speakers."""
    settings = VoiceSettings.from_config(config)
    if settings.listen == "hold":
        settings = dataclasses.replace(settings, listen="wake")
    return LocalVoice(
        bus,
        settings,
        source=FileSource(input_wav, pace=pace),
        sink=WavSink(output_wav, pace=pace),
        models=default_models(settings),
    )
