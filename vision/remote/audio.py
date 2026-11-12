"""Voice notes as audio: decoding what arrives, encoding what is sent back.

A voice note from the phone is Ogg Opus. It is decoded to 16 kHz mono float32
for Whisper by the first decoder this Mac has, in this order:

1. `soundfile`, in process, when its libsndfile reads Ogg Opus (the `voice`
   extra installs it);
2. `afconvert`, which ships with macOS;
3. `ffmpeg`, when it is installed.

None is required; with none the channel says so plainly. A reply voice note
is encoded with `soundfile`, or `ffmpeg`, or not at all (text only).
Everything here blocks; callers use `asyncio.to_thread`.
"""

from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from vision.core.programs import find_program

if TYPE_CHECKING:
    import numpy as np

RATE = 16_000
VOICE_RATE = 48_000
"""Discord's own voice messages are 48 kHz mono Opus."""
WAVEFORM_POINTS = 256
TOOL_TIMEOUT_S = 60


class DecodeFailed(Exception):
    """The audio could not be decoded."""


class Decoder(Protocol):
    name: str

    def available(self) -> bool: ...
    def decode(self, data: bytes) -> np.ndarray:
        """16 kHz mono float32. Raises `DecodeFailed`."""
        ...


def _has(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


class SoundfileDecoder:
    name = "soundfile"

    def available(self) -> bool:
        if not (_has("soundfile") and _has("numpy") and _has("scipy")):
            return False
        import soundfile

        return "OPUS" in soundfile.available_subtypes("OGG")

    def decode(self, data: bytes) -> np.ndarray:
        import io

        import soundfile

        try:
            audio, rate = soundfile.read(io.BytesIO(data), dtype="float32", always_2d=True)
        except (RuntimeError, ValueError, soundfile.LibsndfileError) as exc:
            raise DecodeFailed(str(exc)) from exc
        return _resample(audio.mean(axis=1), rate, RATE)


@dataclass(frozen=True, slots=True)
class ToolDecoder:
    """A command-line converter that writes 16-bit 16 kHz mono WAV."""

    name: str
    args: tuple[str, ...]
    """Arguments after the program, with `{in}` and `{out}` for the two files."""

    def available(self) -> bool:
        return _has("numpy") and find_program(self.name) is not None

    def decode(self, data: bytes) -> np.ndarray:
        program = find_program(self.name)
        if program is None:
            raise DecodeFailed(f"{self.name} is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / "in.ogg", Path(tmp) / "out.wav"
            source.write_bytes(data)
            args = [a.replace("{in}", str(source)).replace("{out}", str(target)) for a in self.args]
            try:
                subprocess.run([str(program), *args], check=True, capture_output=True, timeout=TOOL_TIMEOUT_S)
            except (subprocess.SubprocessError, OSError) as exc:
                raise DecodeFailed(f"{self.name} could not convert it") from exc
            return _read_wav16(target)


AFCONVERT = ToolDecoder("afconvert", ("-f", "WAVE", "-d", f"LEI16@{RATE}", "-c", "1", "{in}", "{out}"))
FFMPEG = ToolDecoder(
    "ffmpeg",
    ("-nostdin", "-v", "error", "-y", "-i", "{in}", "-ac", "1", "-ar", str(RATE), "-c:a", "pcm_s16le", "{out}"),
)


def default_decoders() -> list[Decoder]:
    return [SoundfileDecoder(), AFCONVERT, FFMPEG]


def first_available(decoders: list[Decoder]) -> Decoder | None:
    return next((d for d in decoders if d.available()), None)


def _read_wav16(path: Path) -> np.ndarray:
    import numpy as np

    try:
        with wave.open(str(path), "rb") as wav:
            frames = wav.readframes(wav.getnframes())
            channels, rate, width = wav.getnchannels(), wav.getframerate(), wav.getsampwidth()
    except (OSError, wave.Error, EOFError) as exc:
        raise DecodeFailed("the converted audio could not be read") from exc
    if width != 2:
        raise DecodeFailed("the converted audio is not 16-bit")
    audio = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    return _resample(audio, rate, RATE)


def _resample(audio: np.ndarray, rate: int, target: int) -> np.ndarray:
    import numpy as np

    if rate == target:
        return audio.astype(np.float32, copy=False)
    from math import gcd

    from scipy.signal import resample_poly

    g = gcd(rate, target)
    return resample_poly(audio, target // g, rate // g).astype(np.float32)


# ---------------------------------------------------------------- the way back


def encode_voice(audio: np.ndarray, rate: int) -> bytes | None:
    """48 kHz mono Ogg Opus for a voice message, or None when nothing here can write it."""
    import numpy as np

    mono = np.asarray(audio, dtype=np.float32).reshape(-1)
    if _has("soundfile") and _has("scipy"):
        import io

        import soundfile

        if "OPUS" in soundfile.available_subtypes("OGG"):
            out = io.BytesIO()
            soundfile.write(out, _resample(mono, rate, VOICE_RATE), VOICE_RATE, format="OGG", subtype="OPUS")
            return out.getvalue()
    ffmpeg = find_program("ffmpeg")
    if ffmpeg is None:
        return None
    pcm = (np.clip(mono, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    try:
        done = subprocess.run(
            [str(ffmpeg), "-nostdin", "-v", "error", "-f", "s16le", "-ar", str(rate), "-ac", "1", "-i", "-",
             "-ar", str(VOICE_RATE), "-c:a", "libopus", "-b:a", "32k", "-f", "ogg", "-"],
            input=pcm, capture_output=True, check=True, timeout=TOOL_TIMEOUT_S,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    return done.stdout or None


def waveform(audio: np.ndarray) -> bytes:
    """At most 256 loudness points, one byte each, for the voice message's preview."""
    import numpy as np

    mono = np.abs(np.asarray(audio, dtype=np.float32).reshape(-1))
    if mono.size == 0:
        return bytes(1)
    chunks = np.array_split(mono, min(WAVEFORM_POINTS, mono.size))
    peaks = np.array([c.max() for c in chunks])
    top = float(peaks.max()) or 1.0
    return bytes(int(round(255 * p / top)) for p in peaks)
