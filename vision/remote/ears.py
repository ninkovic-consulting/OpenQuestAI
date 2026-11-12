"""Speech for voice notes: the local Whisper in, the speaking voice out.

While voice runs on the Mac, its loaded models are borrowed (on its own
worker thread). Otherwise the models are loaded here on first use, only when
they are already downloaded: a voice note never starts a 2 GB download. The
speaking voice is Kokoro when downloaded, else macOS `say`.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol

from vision.core.config import Config
from vision.remote.host import Host
from vision.setup import hf_cache

if TYPE_CHECKING:
    import numpy as np

log = logging.getLogger(__name__)


class Ears(Protocol):
    def installed(self) -> bool:
        """True when speech recognition can run here without downloading anything."""
        ...

    async def transcribe(self, audio: np.ndarray) -> str: ...
    async def speak(self, text: str) -> tuple[np.ndarray, int]:
        """Raises when no speaking voice can load."""
        ...

    def close(self) -> None: ...


class LocalEars:
    def __init__(self, host: Host, config: Callable[[], Config]) -> None:
        self._host = host
        self._config = config
        self._worker: Any = None
        self._stt: Any = None
        self._synth: Any = None
        self._lock = asyncio.Lock()

    def _settings(self) -> Any:
        from vision.voice.settings import VoiceSettings

        return VoiceSettings.from_config(self._config())

    def installed(self) -> bool:
        if importlib.util.find_spec("mlx_audio") is None:
            return False
        return hf_cache.cached_size(self._settings().stt_model) is not None

    async def transcribe(self, audio: np.ndarray) -> str:
        voice = self._host.local_voice()
        if voice is not None:
            return await voice.transcribe(audio)
        async with self._lock:
            run = self._run()
            if self._stt is None:
                from vision.voice.stt import WhisperStt

                stt = WhisperStt(self._settings().stt_model)
                await run(stt.load)
                self._stt = stt
            stt = self._stt
            return str(await run(lambda: stt.transcribe(audio)))

    async def speak(self, text: str) -> tuple[np.ndarray, int]:
        voice = self._host.local_voice()
        if voice is not None:
            return await voice.synthesize(text)
        async with self._lock:
            run = self._run()
            if self._synth is None:
                self._synth = await run(self._load_synth)
            synth = self._synth
            return await run(lambda: synth.synth(text)), int(synth.sample_rate)

    def _load_synth(self) -> Any:
        from vision.voice.tts import KokoroSynth, SaySynth

        settings = self._settings()
        if hf_cache.cached_size(settings.tts_model) is not None:
            kokoro = KokoroSynth(settings.tts_model, settings.tts_voice, settings.tts_speed)
            try:
                kokoro.load()
                return kokoro
            except Exception as exc:  # Kokoro is optional here; `say` stands in
                log.warning("Kokoro could not load for a voice reply (%s); using say", exc)
        say = SaySynth(settings.say_voice)
        say.load()
        return say

    def _run(self) -> Callable[[Callable[[], Any]], Any]:
        if self._worker is None:
            from vision.voice.worker import Worker

            self._worker = Worker()
        return self._worker.run  # type: ignore[no-any-return]

    def close(self) -> None:
        if self._worker is not None:
            self._worker.close()
        self._worker = self._stt = self._synth = None
