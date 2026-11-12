"""`LocalVoice`: the models, the audio ends and the loop, as one `Voice`."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from vision.core.bus import Bus
from vision.voice.audio_io import AudioSink, AudioSource
from vision.voice.errors import VoiceUnavailable
from vision.voice.loop import VoiceLoop
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


ModelLoader = Callable[[], Models]
"""Loads every model. Blocking; runs on the model worker."""


def _load(what: str, repo: str, model: _Loadable) -> None:
    started = time.perf_counter()
    try:
        model.load()
    except Exception as exc:
        raise VoiceUnavailable(
            f"{what} could not load ({repo}: {exc}). The first start downloads it from "
            f"Hugging Face, so check the network and the free disk space."
        ) from exc
    log.info("%s loaded in %.1f s", what, time.perf_counter() - started)


def default_models(settings: VoiceSettings) -> ModelLoader:
    def load() -> Models:
        detector = SileroVad(settings.vad_model)
        _load("Voice detection", settings.vad_model, detector)
        transcriber = WhisperStt(settings.stt_model)
        _load("Speech recognition", settings.stt_model, transcriber)
        return Models(detector, transcriber, load_synth(settings))

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
    ) -> None:
        self.bus = bus
        self.settings = settings
        self.source = source
        self.sink = sink
        self._models = models
        self._worker = Worker()
        self._speaker = TtsSpeaker(bus, sink, self._worker.run)
        self.loop: VoiceLoop | None = None
        self._tasks: list[asyncio.Task[None]] = []

    @property
    def speaker(self) -> TtsSpeaker:
        return self._speaker

    async def start(self) -> None:
        if not self.settings.enabled:
            raise VoiceUnavailable("Voice is turned off: [voice] enabled = false in config.toml.")
        try:
            models = await self._worker.run(self._models)
            self.sink.open()
            await self.source.open()
        except BaseException:
            self._worker.close()
            raise
        self._speaker.use(models.synth)
        self.loop = VoiceLoop(
            self.bus,
            self.settings,
            self.source,
            models.detector,
            models.transcriber,
            self._speaker,
            self._worker.run,
        )
        self._tasks = [
            asyncio.create_task(self.loop.watch(), name="voice-watch"),
            asyncio.create_task(self._listen(self.loop), name="voice-listen"),
        ]

    async def _listen(self, loop: VoiceLoop) -> None:
        try:
            await loop.listen()
        except Exception:
            log.exception("the voice loop failed; voice input is off")
            await self.source.close()

    async def stop(self) -> None:
        await self._speaker.stop()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        await self.source.close()
        self._worker.close()
