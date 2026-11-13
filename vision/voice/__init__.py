"""Voice: microphone, VAD, wake matching, speech recognition and speech.

Everything runs locally: Silero VAD, Whisper and Kokoro on MLX (`mlx-audio`),
audio through `sounddevice`. Install with `uv sync --extra voice`. The models
load from the disk only and are never fetched by themselves: the owner
downloads them (Settings, Voice; the wizard; `vision setup`; the doctor's Fix),
and `start()` fails with one plain message naming what is missing.

    voice = make_voice(config, bus)   # no I/O here
    await voice.start()               # loads models; opens the microphone unless it is `hold`
    await voice.speaker.say("Hello.")
    voice.listen("wake")              # the microphone opens now and stays open

`vision.voice.filemode.make_file_voice` runs the same pipeline on WAV files,
and `python -m vision.voice.check` tries the microphone and speakers.
"""

from __future__ import annotations

from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.events import ListenMode, MicState, Notice
from vision.core.interfaces import Speaker, Voice
from vision.voice.errors import VoiceUnavailable


def make_voice(config: Config, bus: Bus) -> Voice:
    """Build the voice loop and its speaker. Models load and devices open in `start()`."""
    try:
        from vision.voice.audio_io import Microphone, SpeakerOutput
        from vision.voice.bluetooth import chosen_are_one_headset
        from vision.voice.service import LocalVoice, default_models
        from vision.voice.settings import VoiceSettings, listen_event
    except ImportError as exc:
        return _NotInstalled(exc)

    settings = VoiceSettings.from_config(config)

    def missing(text: str) -> None:
        bus.publish(Notice(level="warn", text=text))

    return LocalVoice(
        bus,
        settings,
        source=Microphone(settings.input_device, on_missing=missing),
        sink=SpeakerOutput(settings.output_device, on_missing=missing),
        models=default_models(settings),
        on_mic=lambda mic: bus.publish(listen_event(config, mic, voice=True)),
        one_headset=lambda: chosen_are_one_headset(settings.input_device, settings.output_device),
    )


class _NotInstalled:
    """Stands in when the `voice` extra is missing; `start()` says how to install it."""

    mic: MicState = "closed"
    mic_problem: str | None = None

    def __init__(self, error: ImportError) -> None:
        self._error = error

    @property
    def speaker(self) -> Speaker:
        return self

    def listen(self, mode: ListenMode) -> None:
        return None

    async def say(self, sentence: str) -> None:
        return None

    async def start(self) -> None:
        raise VoiceUnavailable(
            f"The voice packages are not installed ({self._error.name}). "
            f"Run `uv sync --extra voice` and restart."
        )

    async def stop(self) -> None:
        return None
