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
"""

from __future__ import annotations

from dataclasses import dataclass

from vision.core.config import Config

DEFAULT_STT_MODEL = "mlx-community/whisper-large-v3-turbo-asr-fp16"
DEFAULT_TTS_MODEL = "mlx-community/Kokoro-82M-bf16"
DEFAULT_TTS_VOICE = "af_heart"
DEFAULT_VAD_MODEL = "mlx-community/silero-vad"


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
        )
