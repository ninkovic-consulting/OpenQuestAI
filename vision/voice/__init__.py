"""Voice: microphone, VAD, wake matching, speech recognition and speech.

Everything runs locally: Silero VAD, Whisper and Kokoro on MLX (`mlx-audio`),
audio through `sounddevice`. Install with `uv sync --extra voice`. The models
download from Hugging Face on the first `start()`.

    voice = make_voice(config, bus)   # no I/O here
    await voice.start()               # loads models, opens the microphone
    await voice.speaker.say("Hello.")

`vision.voice.filemode.make_file_voice` runs the same pipeline on WAV files,
and `python -m vision.voice.check` tries the microphone and speakers.
"""

from __future__ import annotations

from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.interfaces import Speaker, Voice
from vision.voice.errors import VoiceUnavailable


def make_voice(config: Config, bus: Bus) -> Voice:
    """Build the voice loop and its speaker. Models load and devices open in `start()`."""
    try:
        from vision.voice.audio_io import Microphone, SpeakerOutput
        from vision.voice.service import LocalVoice, default_models
        from vision.voice.settings import VoiceSettings
    except ImportError as exc:
        return _NotInstalled(exc)

    settings = VoiceSettings.from_config(config)
    return LocalVoice(
        bus,
        settings,
        source=Microphone(settings.input_device),
        sink=SpeakerOutput(settings.output_device),
        models=default_models(settings),
    )


class _NotInstalled:
    """Stands in when the `voice` extra is missing; `start()` says how to install it."""

    def __init__(self, error: ImportError) -> None:
        self._error = error

    @property
    def speaker(self) -> Speaker:
        return self

    async def say(self, sentence: str) -> None:
        return None

    async def start(self) -> None:
        raise VoiceUnavailable(
            f"The voice packages are not installed ({self._error.name}). "
            f"Run `uv sync --extra voice` and restart."
        )

    async def stop(self) -> None:
        return None
