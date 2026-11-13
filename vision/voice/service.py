"""`LocalVoice`: the models, the audio ends and the loop, as one `Voice`.

The microphone opens and closes as the listening mode asks (`Ears`); the mode
changes with `listen()` at once, without loading anything again.

While it runs it also lends its models to the phone channel (`transcribe`,
`synthesize`), on the same worker thread, so no model runs twice at once.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from vision.core.bus import Bus
from vision.core.events import ListenMode, MicState, Notice
from vision.voice.audio_io import AudioSink, AudioSource
from vision.voice.bluetooth import SETTLE_S
from vision.voice.ears import Ears
from vision.voice.errors import VoiceUnavailable
from vision.voice.loop import VoiceLoop
from vision.voice.on_disk import ModelMissing, require
from vision.voice.settings import VoiceSettings
from vision.voice.stt import Transcriber, WhisperStt
from vision.voice.tts import Synth, TtsSpeaker, load_synth
from vision.voice.vad import SileroVad, SpeechDetector
from vision.voice.worker import Worker

log = logging.getLogger(__name__)


class _Loadable(Protocol):
    def load(self) -> None: ...


@dataclass(frozen=True, slots=True)
class Models:
    detector: SpeechDetector
    transcriber: Transcriber
    synth: Synth
    degraded: str | None = None
    """Why voice runs with less than it should (shown as a notice), or None."""


ModelLoader = Callable[[], Models]
"""Loads every model. Blocking; runs on the model worker."""


def _load(what: str, repo: str, model: _Loadable) -> None:
    started = time.perf_counter()
    try:
        model.load()
    except ModelMissing:
        raise
    except Exception as exc:
        raise VoiceUnavailable(
            f"{what} could not load ({repo}: {exc}). Check the free disk space, or download "
            f"the speech models again in Settings, Voice."
        ) from exc
    log.info("%s loaded in %.1f s", what, time.perf_counter() - started)


def default_models(settings: VoiceSettings) -> ModelLoader:
    """Loads the models from the disk only; a missing one fails before anything loads."""

    def load() -> Models:
        require(settings.parts())
        detector = SileroVad(settings.vad_model)
        _load("Voice detection", settings.vad_model, detector)
        transcriber = WhisperStt(settings.stt_model)
        _load("Speech recognition", settings.stt_model, transcriber)
        synth, degraded = load_synth(settings)
        return Models(detector, transcriber, synth, degraded)

    return load


class LocalVoice:
    """Satisfies `vision.core.interfaces.Voice`. Nothing is loaded or opened before `start()`."""

    def __init__(
        self,
        bus: Bus,
        settings: VoiceSettings,
        *,
        source: AudioSource,
        sink: AudioSink,
        models: ModelLoader,
        on_mic: Callable[[MicState], None] = lambda mic: None,
        one_headset: Callable[[], bool] = lambda: False,
    ) -> None:
        self.bus = bus
        self.settings = settings
        self.source = source
        self.sink = sink
        self._models = models
        self._worker = Worker()
        self._speaker = TtsSpeaker(bus, sink, self._worker.run)
        self.loop: VoiceLoop | None = None
        self.ears: Ears | None = None
        self._on_mic = on_mic
        self._one_headset = one_headset
        """Blocking: whether the microphone and speakers are one Bluetooth headset."""
        self._loaded: Models | None = None
        self._tasks: list[asyncio.Task[None]] = []

    @property
    def speaker(self) -> TtsSpeaker:
        return self._speaker

    @property
    def mic(self) -> MicState:
        return self.ears.mic if self.ears is not None else "closed"

    @property
    def mic_problem(self) -> str | None:
        return self.ears.problem if self.ears is not None else None

    def listen(self, mode: ListenMode) -> None:
        """Change when the microphone is open, now; before `start()`, from then on."""
        self.settings = dataclasses.replace(self.settings, listen=mode)
        if self.ears is not None:
            self.ears.set_mode(mode)

    async def start(self) -> None:
        if not self.settings.enabled:
            raise VoiceUnavailable("Voice is turned off: [voice] enabled = false in config.toml.")
        ears: Ears | None = None
        try:
            models = await self._worker.run(self._models)
            await asyncio.to_thread(self.sink.open)
            loop = VoiceLoop(
                self.bus,
                self.settings,
                models.detector,
                models.transcriber,
                self._speaker,
                self._worker.run,
            )
            ears = Ears(self.source, loop, on_mic=self._on_mic, on_problem=self._said)
            await ears.start()
        except BaseException:
            if ears is not None:
                await ears.stop()
            self._worker.close()
            raise
        loop.on_ptt = ears.ptt
        if await asyncio.to_thread(self._one_headset):
            ears.settle_s = SETTLE_S
            log.info("the microphone and speakers are one Bluetooth headset")
        self._speaker.before_speaking = ears.quiet
        self._speaker.use(models.synth)
        self._loaded = models
        self.loop, self.ears = loop, ears
        if models.degraded is not None:
            self.bus.publish(Notice(level="warn", text=models.degraded))
        self._tasks = [asyncio.create_task(loop.watch(), name="voice-watch")]

    async def transcribe(self, audio: np.ndarray) -> str:
        """Text for 16 kHz mono float32 audio, on the model worker. Only while started."""
        models = self._require()
        return await self._worker.run(lambda: models.transcriber.transcribe(audio))

    async def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        """The speaking voice saying `text`, as audio and its rate. Only while started."""
        synth = self._require().synth
        return await self._worker.run(lambda: synth.synth(text)), synth.sample_rate

    def _require(self) -> Models:
        if self._loaded is None:
            raise VoiceUnavailable("Voice is not running.")
        return self._loaded

    def _said(self, problem: str) -> None:
        self.bus.publish(Notice(level="warn", text=f"{problem} Hold to talk tries the microphone again."))

    async def stop(self) -> None:
        await self._speaker.stop()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        if self.ears is not None:
            await self.ears.stop()
            self.ears = None
        await self.source.close()
        self._loaded = None
        self._worker.close()
