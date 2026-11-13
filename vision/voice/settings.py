"""Voice settings, read from `[voice]` in `config.toml` and the assistant's name.

The core's `VoiceConfig` holds the shared keys; the rest are extra keys of the
same section, with the defaults below:

    [voice]
    input_device = ""          # name fragment or index; "" is the system default
    output_device = ""
    stt_model = "mlx-community/whisper-large-v3-turbo-asr-fp16"
    tts_model = "mlx-community/Kokoro-82M-bf16"
    tts_voice = "af_heart"
    tts_speed = 1.0
    vad_model = "mlx-community/silero-vad"
    max_utterance_s = 15.0
    say_voice = ""             # macOS `say` voice for the fallback; "" is the system voice
    listen = "hold"            # hold, wake or always (`listen_mode`)
    listening = "wake"         # the listening mode last chosen, wake or always

`listen` decides when the microphone is open: `hold` opens it only while
push to talk is held (the default, also for a config without the key),
`wake` and `always` keep it open, answering to the name or to everything.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import get_args

from vision.core.config import Config
from vision.core.events import Listening, ListenMode, MicState, VoiceListen

DEFAULT_STT_MODEL = "mlx-community/whisper-large-v3-turbo-asr-fp16"
DEFAULT_TTS_MODEL = "mlx-community/Kokoro-82M-bf16"
DEFAULT_TTS_VOICE = "af_heart"
DEFAULT_VAD_MODEL = "mlx-community/silero-vad"
SPACY_REPO = "spacy/en_core_web_sm"
"""spaCy's English tagger, which Kokoro's G2P needs; fetched without its wheel."""

STT_PART = "speech recognition"
TTS_PART = "the speaking voice"
VAD_PART = "voice detection"
TAGGER_PART = "the speaking voice's English tagger"

LISTEN_MODES: tuple[ListenMode, ...] = get_args(ListenMode)
LISTENING_MODES: tuple[Listening, ...] = get_args(Listening)
DEFAULT_LISTEN: ListenMode = "hold"
DEFAULT_LISTENING: Listening = "wake"
LISTEN_KEYS = ("listen", "listening")
"""The `[voice]` keys of the listening mode."""


def listen_mode(config: Config) -> ListenMode:
    """`[voice] listen`; `hold` when it is missing or not one of the three."""
    value = (config.voice.model_extra or {}).get("listen", DEFAULT_LISTEN)
    return next((m for m in LISTEN_MODES if m == value), DEFAULT_LISTEN)


def listening_mode(config: Config) -> Listening:
    """`[voice] listening`, the listening mode last chosen; `wake` when there is none."""
    value = (config.voice.model_extra or {}).get("listening", DEFAULT_LISTENING)
    return next((m for m in LISTENING_MODES if m == value), DEFAULT_LISTENING)


def listen_event(config: Config, mic: MicState, *, voice: bool) -> VoiceListen:
    """The `voice.listen` event as `config` says, with the microphone as it is now."""
    gate = config.gate
    return VoiceListen(
        mode=listen_mode(config),
        mic=mic if voice else "closed",
        voice=voice,
        listening=listening_mode(config),
        shell_free=gate.tiers.get("shell", gate.default_tier) == "free",
    )


@dataclass(frozen=True, slots=True)
class VoiceSettings:
    name: str
    enabled: bool = True
    silence_ms: int = 600
    max_utterance_s: float = 15.0
    followup_s: float = 20.0
    stop_phrases: tuple[str, ...] = ("stop", "cancel")
    input_device: str = ""
    output_device: str = ""
    stt_model: str = DEFAULT_STT_MODEL
    tts_model: str = DEFAULT_TTS_MODEL
    tts_voice: str = DEFAULT_TTS_VOICE
    tts_speed: float = 1.0
    vad_model: str = DEFAULT_VAD_MODEL
    say_voice: str = ""
    listen: ListenMode = DEFAULT_LISTEN

    @classmethod
    def from_config(cls, config: Config) -> VoiceSettings:
        v = config.voice
        extra = v.model_extra or {}
        name = config.assistant.name
        return cls(
            name=name,
            enabled=v.enabled,
            silence_ms=v.vad_silence_ms,
            max_utterance_s=float(extra.get("max_utterance_s", 15.0)),
            followup_s=v.followup_window_s,
            stop_phrases=(*v.stop_phrases, f"{name} stop"),
            input_device=str(extra.get("input_device", "")),
            output_device=str(extra.get("output_device", "")),
            stt_model=str(extra.get("stt_model", DEFAULT_STT_MODEL)),
            tts_model=str(extra.get("tts_model", DEFAULT_TTS_MODEL)),
            tts_voice=str(extra.get("tts_voice", DEFAULT_TTS_VOICE)),
            tts_speed=float(extra.get("tts_speed", 1.0)),
            vad_model=str(extra.get("vad_model", DEFAULT_VAD_MODEL)),
            say_voice=str(extra.get("say_voice", "")),
            listen=listen_mode(config),
        )

    def parts(self) -> dict[str, str]:
        """Every model voice needs, by the name a message gives it. Downloaded only on request."""
        return {
            STT_PART: self.stt_model,
            TTS_PART: self.tts_model,
            VAD_PART: self.vad_model,
            TAGGER_PART: SPACY_REPO,
        }

    def speech_parts(self) -> dict[str, str]:
        """The models the speaking voice alone needs: Kokoro and spaCy's tagger for its G2P."""
        return {TTS_PART: self.tts_model, TAGGER_PART: SPACY_REPO}

    def model_repos(self) -> tuple[str, ...]:
        """Every Hugging Face repo voice needs; the speech-models download fetches them."""
        return tuple(self.parts().values())

    def speech_repos(self) -> tuple[str, ...]:
        return tuple(self.speech_parts().values())
