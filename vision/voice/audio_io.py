"""Microphone capture (16 kHz mono) and speaker playback through `sounddevice`.

`AudioSource` and `AudioSink` are the seams the voice loop uses, so file mode
(`vision.voice.filemode`) can stand in for the hardware.

Playback runs one output stream per sentence with 20 ms blocks; `stop()` makes
the next block silent and ends the stream, so speech stops within one block
plus the device's latency, well inside 100 ms. `levels()` computes the output
level envelope the speaker publishes while a sentence plays.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator
from typing import Any, Literal, Protocol

import numpy as np

from vision.voice.errors import VoiceUnavailable, mic_permission_hint
from vision.voice.vad import FRAME, SAMPLE_RATE

LEVEL_RATE = 30
"""Level envelope frames per second."""


class AudioSource(Protocol):
    async def open(self) -> None:
        """Start capturing. Raise `VoiceUnavailable` when that is impossible."""
        ...

    def chunks(self) -> AsyncIterator[np.ndarray]:
        """16 kHz mono float32 chunks, in order, until the source ends or closes."""
        ...

    async def close(self) -> None: ...


class AudioSink(Protocol):
    def open(self) -> None:
        """Get ready to play. Raise `VoiceUnavailable` when that is impossible."""
        ...

    async def play(self, audio: np.ndarray, sample_rate: int) -> bool:
        """Play mono float32 audio; True when it finished, False when stopped."""
        ...

    def stop(self) -> None:
        """Stop the audio playing now. Safe when silent."""
        ...

    def position(self) -> float:
        """Seconds of the current audio played so far."""
        ...


def levels(audio: np.ndarray, sample_rate: int, rate: int = LEVEL_RATE) -> np.ndarray:
    """Loudness 0..1 per 1/`rate` s, on a -50..0 dBFS scale."""
    step = max(1, sample_rate // rate)
    n = max(1, -(-len(audio) // step))
    padded = np.zeros(n * step, dtype=np.float32)
    padded[: len(audio)] = audio
    rms = np.sqrt(np.mean(padded.reshape(n, step) ** 2, axis=1))
    db = 20 * np.log10(np.maximum(rms, 1e-6))
    return np.clip((db + 50) / 50, 0.0, 1.0)


def _sd() -> Any:
    try:
        import sounddevice
    except OSError as exc:  # PortAudio missing
        raise VoiceUnavailable(f"Audio devices are unavailable: {exc}") from exc
    return sounddevice


def describe_devices() -> str:
    """The audio devices, one per line, as `sounddevice` lists them."""
    return str(_sd().query_devices())


def find_device(spec: str, kind: Literal["input", "output"]) -> int | None:
    """Resolve a configured device: "" is the default, a number an index, else a name fragment."""
    spec = spec.strip()
    if not spec:
        return None
    if spec.isdigit():
        return int(spec)
    channels = f"max_{kind}_channels"
    for index, dev in enumerate(_sd().query_devices()):
        if dev[channels] > 0 and spec.lower() in dev["name"].lower():
            return index
    raise VoiceUnavailable(
        f"No {kind} device matches {spec!r}. Run `python -m vision.voice.check` "
        f"to list devices, then fix `{kind}_device` under [voice] in config.toml."
    )


class Microphone:
    """Captures 16 kHz mono in 32 ms chunks. Audio callbacks hand over to the loop."""

    def __init__(self, device: str = "", probe_s: float = 0.5) -> None:
        self.device = device
        self.probe_s = probe_s
        self._queue: asyncio.Queue[np.ndarray | None] = asyncio.Queue()
        self._head: list[np.ndarray] = []
        self._stream: Any = None

    async def open(self) -> None:
        sd = _sd()
        loop = asyncio.get_running_loop()
        device = find_device(self.device, "input")

        def callback(indata: np.ndarray, frames: int, t: Any, status: Any) -> None:
            chunk = indata[:, 0].copy()
            try:
                loop.call_soon_threadsafe(self._queue.put_nowait, chunk)
            except RuntimeError:  # the loop closed under us
                pass

        try:
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=FRAME,
                device=device,
                callback=callback,
            )
            await asyncio.to_thread(self._stream.start)
        except sd.PortAudioError as exc:
            raise VoiceUnavailable(f"The microphone could not open ({exc}). {mic_permission_hint()}") from exc
        await self._check_permission()

    async def _check_permission(self) -> None:
        """macOS hands a denied app pure digital silence instead of an error."""
        wanted = max(1, round(self.probe_s * SAMPLE_RATE / FRAME))
        try:
            async with asyncio.timeout(self.probe_s + 2.0):
                while len(self._head) < wanted:
                    chunk = await self._queue.get()
                    if chunk is not None:
                        self._head.append(chunk)
        except TimeoutError:
            await self.close()
            raise VoiceUnavailable(f"The microphone sends no audio. {mic_permission_hint()}") from None
        if not any(np.any(chunk) for chunk in self._head):
            await self.close()
            raise VoiceUnavailable(f"The microphone sends only silence. {mic_permission_hint()}")

    async def chunks(self) -> AsyncIterator[np.ndarray]:
        head, self._head = self._head, []
        for chunk in head:
            yield chunk
        while (chunk := await self._queue.get()) is not None:
            yield chunk

    async def close(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            await asyncio.to_thread(stream.close)
        self._queue.put_nowait(None)


class SpeakerOutput:
    """Plays audio on the configured output device, stoppable mid-sentence."""

    BLOCK_S = 0.02

    def __init__(self, device: str = "") -> None:
        self.device = device
        self._index: int | None = None
        self._stop = threading.Event()
        self._played = 0
        self._rate = 1

    def open(self) -> None:
        """Resolve the device now so a wrong name fails at start-up."""
        self._index = find_device(self.device, "output")

    def stop(self) -> None:
        self._stop.set()

    def position(self) -> float:
        return self._played / self._rate

    async def play(self, audio: np.ndarray, sample_rate: int) -> bool:
        stop = self._stop = threading.Event()
        self._played, self._rate = 0, sample_rate
        sd = _sd()
        loop = asyncio.get_running_loop()
        done = asyncio.Event()
        data = audio.astype(np.float32, copy=False)

        def callback(outdata: np.ndarray, frames: int, t: Any, status: Any) -> None:
            chunk = data[self._played : self._played + frames]
            if stop.is_set():
                outdata.fill(0)
                raise sd.CallbackStop
            outdata[: len(chunk), 0] = chunk
            outdata[len(chunk) :] = 0
            self._played += len(chunk)
            if len(chunk) < frames:
                raise sd.CallbackStop

        def finished() -> None:
            try:
                loop.call_soon_threadsafe(done.set)
            except RuntimeError:
                pass

        stream = sd.OutputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
            blocksize=max(1, int(sample_rate * self.BLOCK_S)),
            latency="low",
            device=self._index,
            callback=callback,
            finished_callback=finished,
        )
        try:
            await asyncio.to_thread(stream.start)
            await done.wait()
        finally:
            await asyncio.to_thread(stream.close)
        return not stop.is_set()
