"""Microphone capture (16 kHz mono) and speaker playback through `sounddevice`.

`AudioSource` and `AudioSink` are the seams the voice loop uses, so file mode
(`vision.voice.filemode`) can stand in for the hardware.

Playback runs one output stream per sentence with 20 ms blocks; `stop()` makes
the next block silent and ends the stream, so speech stops within one block
plus the device's latency, well inside 100 ms. `levels()` computes the output
level envelope the speaker publishes while a sentence plays.

PortAudio reads the device list once, when it initialises, so a device
plugged in later (AirPods connected while the assistant runs) cannot be
opened until it initialises again. `refresh_devices()` does that before a
microphone or speaker opens, but only while no stream is open: initialising
again invalidates every open stream. A configured device that is not
connected falls back to the system default, and `on_missing` hears why.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator, Callable
from typing import Any, Literal, Protocol

import numpy as np

from vision.voice.errors import VoiceUnavailable, mic_permission_hint, silent_mic_hint
from vision.voice.vad import FRAME, SAMPLE_RATE

LEVEL_RATE = 30
"""Level envelope frames per second."""
SOUND_WAIT_S = 3.0
"""How long a newly opened microphone may send only zeros. AirPods take about half a second."""
NO_AUDIO_GRACE_S = 2.0
"""Beyond `SOUND_WAIT_S`, how long to wait for the first chunk at all."""

Kind = Literal["input", "output"]
Missing = Callable[[str], None]
"""Hears why a configured device is not used (it is not connected), in words for a notice."""
WHAT: dict[Kind, str] = {"input": "microphone", "output": "speakers"}


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


_streams = 0
_streams_lock = threading.Lock()


def _count(change: int) -> None:
    """Count streams from before one is built until it is closed, so no refresh breaks one."""
    global _streams
    with _streams_lock:
        _streams += change


def refresh_devices() -> bool:
    """Make PortAudio see the devices as they are now; False when a stream is open.

    Blocking (it initialises CoreAudio again). sounddevice has no public call
    for this, so it uses the two it runs itself at import and at exit.
    """
    sd = _sd()
    with _streams_lock:
        if _streams:
            return False
        sd._terminate()
        sd._initialize()
    return True


def describe_devices() -> str:
    """The audio devices, one per line, as `sounddevice` lists them."""
    return str(_sd().query_devices())


def device_name(index: int | None, kind: Kind) -> str:
    """The name of a device by index; None is the system default."""
    return str(_sd().query_devices(index, kind=kind)["name"])


def resolve_device(spec: str, kind: Kind) -> tuple[int | None, str | None]:
    """A configured device as an index, and why it is not the one asked for.

    "" is the system default, a number an index, else a name fragment. A name
    that matches no connected device gives the system default (None) and a
    line saying so.
    """
    spec = spec.strip()
    if not spec:
        return None, None
    if spec.isdigit():
        return int(spec), None
    channels = f"max_{kind}_channels"
    for index, dev in enumerate(_sd().query_devices()):
        if dev[channels] > 0 and spec.lower() in dev["name"].lower():
            return index, None
    fallback = device_name(None, kind)
    return None, (
        f"The {WHAT[kind]} “{spec}” {'is' if kind == 'input' else 'are'} not connected, "
        f"so the system default ({fallback}) is used."
    )


class Microphone:
    """Captures 16 kHz mono in 32 ms chunks. Audio callbacks hand over to the loop."""

    def __init__(
        self, device: str = "", wait_s: float = SOUND_WAIT_S, on_missing: Missing | None = None
    ) -> None:
        self.device = device
        self.wait_s = wait_s
        self.name = ""
        """The device opened, by name; set by `open()`."""
        self._on_missing = on_missing
        self._queue: asyncio.Queue[np.ndarray | None] = asyncio.Queue()
        self._head: list[np.ndarray] = []
        self._stream: Any = None
        self._counted = False

    async def open(self) -> None:
        sd = _sd()
        loop = asyncio.get_running_loop()
        await asyncio.to_thread(refresh_devices)
        device, missing = resolve_device(self.device, "input")
        if missing is not None and self._on_missing is not None:
            self._on_missing(missing)
        self.name = device_name(device, "input")

        def callback(indata: np.ndarray, frames: int, t: Any, status: Any) -> None:
            chunk = indata[:, 0].copy()
            try:
                loop.call_soon_threadsafe(self._queue.put_nowait, chunk)
            except RuntimeError:  # the loop closed under us
                pass

        _count(+1)
        self._counted = True
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
            await self.close()
            raise VoiceUnavailable(
                f"The microphone “{self.name}” could not open ({exc}). {mic_permission_hint()}"
            ) from exc
        await self._wait_for_sound()

    async def _wait_for_sound(self) -> None:
        """Wait for the first sample that is not zero, for up to `wait_s` of audio.

        A microphone that is muted, asleep or covered sends zeros, and so does
        any microphone to an app macOS has not allowed. Some devices take a
        moment to wake (AirPods about half a second), so the wait ends at the
        first sound rather than after a fixed time. The audio read here is kept
        for `chunks()`.
        """
        wanted = max(1, round(self.wait_s * SAMPLE_RATE))
        got = 0
        try:
            async with asyncio.timeout(self.wait_s + NO_AUDIO_GRACE_S):
                while got < wanted:
                    chunk = await self._queue.get()
                    if chunk is None:
                        break
                    self._head.append(chunk)
                    got += len(chunk)
                    if np.any(chunk):
                        return
        except TimeoutError:
            pass
        await self.close()
        heard = "sends only silence" if got else "sends no audio"
        raise VoiceUnavailable(f"The microphone “{self.name}” {heard}. {silent_mic_hint()}")

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
        if self._counted:
            self._counted = False
            _count(-1)
        self._queue.put_nowait(None)


class SpeakerOutput:
    """Plays audio on the configured output device, stoppable mid-sentence.

    The device is looked up again for every sentence, so speech follows the
    device list after a refresh, and falls back to the system default (saying
    so once) while the chosen speakers are not connected.
    """

    BLOCK_S = 0.02

    def __init__(self, device: str = "", on_missing: Missing | None = None) -> None:
        self.device = device
        self._on_missing = on_missing
        self._said: str | None = None
        self._stop = threading.Event()
        self._played = 0
        self._rate = 1

    def open(self) -> None:
        """See the devices as they are now. Blocking."""
        refresh_devices()
        self._resolve()

    def _resolve(self) -> int | None:
        index, missing = resolve_device(self.device, "output")
        if missing is not None and missing != self._said and self._on_missing is not None:
            self._on_missing(missing)
        self._said = missing
        return index

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

        _count(+1)
        try:
            stream = sd.OutputStream(
                samplerate=sample_rate,
                channels=1,
                dtype="float32",
                blocksize=max(1, int(sample_rate * self.BLOCK_S)),
                latency="low",
                device=self._resolve(),
                callback=callback,
                finished_callback=finished,
            )
            try:
                await asyncio.to_thread(stream.start)
                await done.wait()
            finally:
                await asyncio.to_thread(stream.close)
        finally:
            _count(-1)
        return not stop.is_set()
