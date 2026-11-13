"""Speech: Kokoro on MLX, one sentence at a time, with macOS `say` as the fallback.

`KokoroSynth` runs `mlx-community/Kokoro-82M-bf16` through `mlx-audio`, with
misaki for English pronunciation. misaki wants to pip-install its spaCy model
on first use, which does not work in a uv environment, so the model is loaded
from spaCy's own Hugging Face repository instead. Both load from the disk
only (`on_disk`): a missing one fails, it is never fetched. espeak-ng (bundled
by `espeakng-loader`) spells out words misaki does not know.

`TtsSpeaker` is the `Speaker` the session uses: it synthesises a sentence on
the model worker, plays it, and publishes `voice.level` about 30 times a
second while it plays. `stop()` cuts the sentence off and drops it. `chime()`
plays the short sound that marks the start of thinking.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import tempfile
import time
import warnings
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TypeVar

import numpy as np

from vision.core.bus import Bus
from vision.core.events import VoiceLevel
from vision.voice.audio_io import LEVEL_RATE, AudioSink, levels
from vision.voice.errors import VoiceUnavailable
from vision.voice.on_disk import local_path
from vision.voice.settings import SPACY_REPO, TAGGER_PART, TTS_PART, VoiceSettings
from vision.voice.wake import words

log = logging.getLogger(__name__)

T = TypeVar("T")
Run = Callable[[Callable[[], T]], Awaitable[T]]

ESPEAK_MAX_PATH = 150
"""espeak-ng keeps its data path in a 160-byte buffer and exits the process if it overflows."""


class Synth(Protocol):
    sample_rate: int

    def synth(self, text: str) -> np.ndarray:
        """Mono float32 audio for one sentence. Blocking."""
        ...


class KokoroSynth:
    sample_rate = 24_000

    def __init__(self, repo: str, voice: str, speed: float = 1.0) -> None:
        self.repo = repo
        self.voice = voice
        self.speed = speed
        self._pipeline: Any = None

    def load(self) -> None:
        from mlx_audio.tts.models.kokoro.pipeline import KokoroPipeline
        from mlx_audio.tts.utils import load

        folder = local_path(self.repo, TTS_PART)
        # A `Path`, not text: from text mlx-audio takes the model's name from the last folder,
        # which in the cache is a commit hash, and then cannot tell which model this is.
        model = load(folder)
        # KokoroPipeline.__init__ would build misaki's G2P, which pip-installs spaCy's model.
        pipeline = KokoroPipeline.__new__(KokoroPipeline)
        pipeline.lang_code = "a"
        pipeline.repo_id = self.repo
        pipeline.model_path = folder  # the voices load from the same snapshot, never the Hub
        pipeline.model = model
        pipeline.voices = {}
        pipeline.g2p = _english_g2p()
        pipeline.load_voice(self.voice)
        self._pipeline = pipeline
        self.synth("Ready.")  # compile the kernels once

    def synth(self, text: str) -> np.ndarray:
        parts = [
            np.asarray(result.audio, dtype=np.float32).reshape(-1)
            for result in self._pipeline(text, voice=self.voice, speed=self.speed)
            if result.audio is not None
        ]
        return np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)


def _english_g2p() -> Any:
    """misaki's American English G2P, with spaCy's tagger from the Hugging Face Hub."""
    import espeakng_loader
    import spacy
    from misaki import en, espeak

    nlp_dir = local_path(SPACY_REPO, TAGGER_PART)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=r".*\[W095\]")  # 3.7 model on spaCy 3.8
        nlp = spacy.load(nlp_dir, enable=["tok2vec", "tagger"])
    fallback = None
    if len(espeakng_loader.get_data_path()) < ESPEAK_MAX_PATH:
        fallback = espeak.EspeakFallback(british=False)
    else:
        log.warning("espeak-ng data path is too long; unknown words will be skipped")
    g2p = en.G2P.__new__(en.G2P)  # the same fields misaki 0.9.4's __init__ sets
    g2p.version = None
    g2p.british = False
    g2p.nlp = nlp
    g2p.lexicon = en.Lexicon(False)
    g2p.fallback = fallback
    g2p.unk = ""
    return g2p


class SaySynth:
    """macOS `say`, rendered to audio so playback, levels and stop work the same."""

    sample_rate = 24_000

    def __init__(self, voice: str = "") -> None:
        self.voice = voice

    def load(self) -> None:
        if shutil.which("say") is None:
            raise VoiceUnavailable("macOS `say` is not available")
        self.synth("Ready.")

    def synth(self, text: str) -> np.ndarray:
        import soundfile

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "say.wav"
            cmd = ["say", "-o", str(out), "--file-format=WAVE", f"--data-format=LEF32@{self.sample_rate}"]
            if self.voice:
                cmd += ["-v", self.voice]
            subprocess.run([*cmd, "--", text], check=True, capture_output=True, timeout=60)
            audio, _ = soundfile.read(out, dtype="float32", always_2d=True)
        return audio[:, 0].copy()


def load_synth(settings: VoiceSettings) -> tuple[Synth, str | None]:
    """Kokoro if it loads, else macOS `say`, with a line for the user when it fell back.

    Blocking: loads models.
    """
    kokoro = KokoroSynth(settings.tts_model, settings.tts_voice, settings.tts_speed)
    try:
        kokoro.load()
        return kokoro, None
    except Exception as exc:
        log.warning("Kokoro could not load (%s); falling back to macOS say", exc)
        kokoro_error = exc
    say = SaySynth(settings.say_voice)
    try:
        say.load()
    except Exception as exc:
        raise VoiceUnavailable(
            f"Speech output could not load: Kokoro failed ({kokoro_error}) and macOS `say` "
            f"failed ({exc})."
        ) from exc
    reason = (str(kokoro_error).strip().splitlines() or [type(kokoro_error).__name__])[0]
    return say, (
        f"Speech is using the macOS voice because Kokoro could not load ({reason[:160]}). "
        "Download the speech models in Settings, Voice, or check the free disk space, then "
        "turn voice off and on to try again."
    )


def _chime(rate: int) -> np.ndarray:
    notes = []
    for freq in (660.0, 880.0):
        t = np.arange(int(0.07 * rate)) / rate
        notes.append(0.12 * np.sin(2 * np.pi * freq * t) * np.hanning(len(t)))
    return np.concatenate(notes).astype(np.float32)


CHIME_RATE = 24_000
CHIME = _chime(CHIME_RATE)


@dataclass(frozen=True, slots=True)
class Spoken:
    text: str
    started: float
    ended: float


class TtsSpeaker:
    """Speaks one sentence at a time and reports what it said, for the echo guard."""

    def __init__(self, bus: Bus, sink: AudioSink, run: Run[Any], clock: Callable[[], float] = time.monotonic) -> None:
        self._bus = bus
        self._sink = sink
        self._run = run
        self._clock = clock
        self._synth: Synth | None = None
        self._generation = 0
        self._spoken: deque[Spoken] = deque(maxlen=32)
        self._playing = asyncio.Lock()
        self.current: Spoken | None = None

    def use(self, synth: Synth) -> None:
        self._synth = synth

    @property
    def playing(self) -> bool:
        return self.current is not None

    @property
    def last_end(self) -> float:
        return self._spoken[-1].ended if self._spoken else float("-inf")

    def spoken_since(self, since: float) -> list[str]:
        """Sentences playing at or after `since`, oldest first."""
        out = [s.text for s in self._spoken if s.ended >= since]
        if self.current is not None:
            out.append(self.current.text)
        return out

    async def say(self, sentence: str) -> None:
        synth = self._synth
        if synth is None:
            raise RuntimeError("the speaker is not started")
        text = sentence.strip()
        if not words(text):
            return
        generation = self._generation
        audio = await self._run(lambda: synth.synth(text))
        async with self._playing:
            if generation != self._generation or audio.size == 0:
                return
            started = self._clock()
            self.current = Spoken(text, started, started)
            meter = asyncio.create_task(self._meter(levels(audio, synth.sample_rate)))
            try:
                await self._sink.play(audio, synth.sample_rate)
            finally:
                meter.cancel()
                await asyncio.gather(meter, return_exceptions=True)
                self._bus.publish(VoiceLevel(level=0.0))
                self._spoken.append(Spoken(text, started, self._clock()))
                self.current = None

    async def chime(self) -> None:
        """A short soft two-note sound: the assistant has started thinking."""
        async with self._playing:
            await self._sink.play(CHIME, CHIME_RATE)

    async def stop(self) -> None:
        self._generation += 1
        self._sink.stop()

    async def _meter(self, envelope: np.ndarray) -> None:
        last = len(envelope) - 1
        while True:
            i = min(int(self._sink.position() * LEVEL_RATE), last)
            self._bus.publish(VoiceLevel(level=float(envelope[i])))
            await asyncio.sleep(1 / LEVEL_RATE)
