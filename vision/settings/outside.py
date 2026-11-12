"""Everything the settings screen touches outside this process, behind one interface.

Tests hand `SettingsService` a fake; the real `MacOutside` reaches the Models
API, the Keychain, Hugging Face and the audio devices, importing each lazily.
None of these methods may log or return the API key.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

import keyring
from keyring.errors import PasswordDeleteError

from vision.core import secrets
from vision.core.config import Config
from vision.setup import hf_cache
from vision.setup.system import MacSystem, System

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    import numpy as np

VOICE_MODULES = ("mlx_audio", "sounddevice")
MODELS_TIMEOUT_S = 15.0


class KeyRefused(Exception):
    """The API refused the key (authentication or permission)."""


class Unreachable(Exception):
    """The API could not be reached, or answered with another error."""


@dataclass(frozen=True, slots=True)
class ModelRow:
    """One model as the Models API lists it."""

    id: str
    display_name: str
    max_input_tokens: int | None
    max_tokens: int | None
    retires_at: str | None
    """`YYYY-MM-DD`, or None when no retirement is scheduled."""


@dataclass(frozen=True, slots=True)
class AudioDevice:
    name: str
    inputs: int
    outputs: int
    default_input: bool
    default_output: bool


class Outside(Protocol):
    def api_key(self) -> str | None: ...
    def key_source(self) -> str | None: ...
    def store_key(self, key: str) -> None: ...
    def delete_key(self) -> None: ...
    def list_models(self, key: str) -> list[ModelRow]:
        """Raises `KeyRefused` or `Unreachable`."""
        ...

    def voice_installed(self) -> bool: ...
    def audio_devices(self) -> list[AudioDevice]:
        """Lists the devices without opening any."""
        ...

    async def mic_test(self, config: Config, seconds: float) -> str:
        """Record, transcribe and say back what was heard; returns the text heard.

        Raises `VoiceUnavailable` (or ImportError) when it cannot.
        """
        ...

    def cached_size(self, repo: str, needs: str = "*") -> int | None: ...
    def download_size(self, repos: list[str]) -> int | None: ...
    def download(self, repos: list[str]) -> None: ...
    def download_local_model(self, config: Config) -> None: ...
    def build_window(self) -> bool: ...
    def doctor_system(self) -> System: ...


def _day(value: datetime | None) -> str | None:
    return value.date().isoformat() if value is not None else None


class MacOutside:
    """The real Mac."""

    def __init__(self) -> None:
        self._system = MacSystem()

    def api_key(self) -> str | None:
        return secrets.get_api_key()

    def key_source(self) -> str | None:
        return secrets.api_key_source()

    def store_key(self, key: str) -> None:
        secrets.store_api_key(key)

    def delete_key(self) -> None:
        try:
            keyring.delete_password(secrets.KEYRING_SERVICE, secrets.KEYRING_ACCOUNT)
        except PasswordDeleteError:
            return

    def list_models(self, key: str) -> list[ModelRow]:
        import anthropic

        try:
            with anthropic.Anthropic(
                api_key=key, timeout=MODELS_TIMEOUT_S, max_retries=0
            ) as client:
                return [
                    ModelRow(
                        id=m.id,
                        display_name=m.display_name,
                        max_input_tokens=m.max_input_tokens,
                        max_tokens=m.max_tokens,
                        retires_at=_day(m.retires_at),
                    )
                    for m in client.models.list(limit=100)
                    if m.lifecycle != "retired"
                ]
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError):
            raise KeyRefused from None
        except anthropic.APIError:
            raise Unreachable from None

    def voice_installed(self) -> bool:
        return all(self._system.has_module(m) for m in VOICE_MODULES)

    def audio_devices(self) -> list[AudioDevice]:
        if importlib.util.find_spec("sounddevice") is None:
            return []
        import sounddevice

        default_in, default_out = sounddevice.default.device
        return [
            AudioDevice(
                name=str(dev["name"]),
                inputs=int(dev["max_input_channels"]),
                outputs=int(dev["max_output_channels"]),
                default_input=index == default_in,
                default_output=index == default_out,
            )
            for index, dev in enumerate(sounddevice.query_devices())
        ]

    async def mic_test(self, config: Config, seconds: float) -> str:
        from vision.core.bus import Bus
        from vision.voice.audio_io import Microphone, SpeakerOutput
        from vision.voice.settings import VoiceSettings
        from vision.voice.stt import WhisperStt
        from vision.voice.tts import TtsSpeaker, load_synth
        from vision.voice.worker import Worker

        settings = VoiceSettings.from_config(config)
        worker = Worker()
        try:
            stt = WhisperStt(settings.stt_model)
            await worker.run(stt.load)
            synth, _ = await worker.run(lambda: load_synth(settings))
            mic = Microphone(settings.input_device)
            await mic.open()
            try:
                audio = await _record(mic.chunks(), seconds)
            finally:
                await mic.close()
            heard: str = await worker.run(lambda: stt.transcribe(audio))
            sink = SpeakerOutput(settings.output_device)
            sink.open()
            speaker = TtsSpeaker(Bus(), sink, worker.run)
            speaker.use(synth)
            await speaker.say(f"I heard: {heard}" if heard else "I did not hear anything.")
            return heard
        finally:
            worker.close()

    def cached_size(self, repo: str, needs: str = "*") -> int | None:
        return hf_cache.cached_size(repo, needs=needs)

    def download_size(self, repos: list[str]) -> int | None:
        return self._system.download_size(repos)

    def download(self, repos: list[str]) -> None:
        self._system.download(repos)

    def download_local_model(self, config: Config) -> None:
        self._system.download_local_model(config)

    def build_window(self) -> bool:
        return self._system.build_window()

    def doctor_system(self) -> System:
        return self._system


async def _record(chunks: AsyncIterator[np.ndarray], seconds: float) -> np.ndarray:
    import numpy as np

    from vision.voice.vad import SAMPLE_RATE

    wanted = int(seconds * SAMPLE_RATE)
    got: list[np.ndarray] = []
    async for chunk in chunks:
        got.append(chunk)
        if sum(len(c) for c in got) >= wanted:
            break
    return np.concatenate(got)[:wanted] if got else np.zeros(0, dtype=np.float32)
