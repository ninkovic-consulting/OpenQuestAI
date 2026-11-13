"""Voice from the settings screen: its state, the devices, on and off, and the tests.

Only `switch` and `test` ever open the microphone, and only when the user asks.
`speak_test` only plays a sentence.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal

from vision.settings.outside import Outside
from vision.settings.values import KOKORO_VOICES
from vision.setup.config_file import update_config
from vision.voice.errors import MIC_SETTING
from vision.voice.on_disk import missing_message
from vision.voice.settings import VoiceSettings

if TYPE_CHECKING:
    from vision.app import Daemon

log = logging.getLogger(__name__)

Mic = Literal["granted", "denied", "silent", "unknown"]
TEST_SECONDS = 3.0
SILENT_SIGNS = ("sends only silence", "sends no audio")
"""The microphone opened but sent nothing: usually the device, not the permission."""
DENIED_SIGNS = (MIC_SETTING,)


def classify(running: bool, error: str | None) -> tuple[Mic, str | None]:
    """What the last attempt to open the microphone says about it and the permission."""
    if running:
        return "granted", None
    if error is not None and any(sign in error for sign in SILENT_SIGNS):
        return "silent", error
    if error is not None and any(sign in error for sign in DENIED_SIGNS):
        return "denied", error
    return "unknown", error


class VoiceControl:
    def __init__(self, daemon: Daemon, outside: Callable[[], Outside]) -> None:
        self._daemon = daemon
        self._outside = outside
        self._last: tuple[Mic, str | None] | None = None
        """The settings screen's own last attempt; before one, the daemon's start-up."""

    def state(self) -> dict[str, Any]:
        """The `voice` object of GET /api/settings. Reads the disk; run it off the loop."""
        d = self._daemon
        outside = self._outside()
        settings = VoiceSettings.from_config(d.config)
        sizes = [outside.cached_size(repo) for repo in settings.model_repos()]
        have = [s for s in sizes if s is not None]
        error = d.voice_error if d.config.voice.enabled else None
        mic, detail = self._last or classify(d.voice_running, error)
        return {
            "installed": outside.voice_installed(),
            "enabled": d.config.voice.enabled,
            "running": d.voice_running,
            "mic": mic,
            "mic_detail": detail,
            "input_device": settings.input_device,
            "output_device": settings.output_device,
            "tts_voice": settings.tts_voice,
            "followup_s": settings.followup_s,
            "models_downloaded": len(have) == len(sizes),
            "models_size_bytes": sum(have) if len(have) == len(sizes) else None,
        }

    def forget(self) -> None:
        """The voice settings changed: what the screen last learnt is about other devices."""
        self._last = None

    def devices(self) -> dict[str, Any]:
        """Lists the audio devices as they are now, without opening any. Blocking."""
        outside = self._outside()
        installed = outside.voice_installed()
        found = outside.audio_devices() if installed else []
        return {
            "installed": installed,
            "inputs": [{"name": d.name, "default": d.default_input} for d in found if d.inputs],
            "outputs": [{"name": d.name, "default": d.default_output} for d in found if d.outputs],
            "voices": list(KOKORO_VOICES),
        }

    async def switch(self, enabled: bool) -> None:
        """Save `[voice] enabled` and turn the microphone loop on or off now."""
        d = self._daemon
        await asyncio.to_thread(
            update_config, d.config.paths.config_file, "voice", {"enabled": enabled}
        )
        d.config.voice.enabled = enabled
        await d.set_voice(enabled)
        if enabled:
            self._last = classify(d.voice_running, d.voice_error)

    async def test(self) -> dict[str, Any]:
        """Record three seconds, transcribe them and say them back."""
        d = self._daemon
        outside = self._outside()
        if not outside.voice_installed():
            return _failed(
                "Voice is not installed. Run `uv sync --extra voice`, then restart the assistant."
            )
        parts = VoiceSettings.from_config(d.config).parts()
        if gone := [part for part, repo in parts.items() if outside.cached_size(repo) is None]:
            return _failed(missing_message(gone))
        try:
            heard = await outside.mic_test(d.config, TEST_SECONDS)
        except Exception as exc:
            log.warning("voice test failed: %s", exc)
            self._last = classify(False, str(exc))
            if self._last[0] == "silent":
                return _failed(str(exc))
            if self._last[0] == "denied":
                return _failed(
                    f"{d.config.assistant.name} cannot hear the microphone. Allow it in "
                    f"{MIC_SETTING}, then try again."
                )
            return _failed(f"The test did not work: {exc}")
        self._last = ("granted", None)
        if not heard:
            return {
                "ok": False,
                "heard": "",
                "message": "Nothing was heard. Check the input device and speak a little louder.",
            }
        return {"ok": True, "heard": heard, "message": f"Heard: {heard}"}

    async def speak_test(self, voice: str | None = None, output_device: str | None = None) -> dict[str, Any]:
        """Say one sentence in the chosen voice through the chosen speakers.

        `voice` and `output_device` override the saved ones, so the screen can
        try a choice before it is saved. Needs only the speaking voice's models.
        """
        d = self._daemon
        outside = self._outside()
        if not outside.voice_installed():
            return _said(
                False,
                "Voice is not installed. Run `uv sync --extra voice`, then restart the assistant.",
            )
        settings = VoiceSettings.from_config(d.config)
        settings = dataclasses.replace(
            settings,
            tts_voice=settings.tts_voice if voice is None else voice,
            output_device=settings.output_device if output_device is None else output_device,
        )
        parts = settings.speech_parts()
        if gone := [part for part, repo in parts.items() if outside.cached_size(repo) is None]:
            return _said(False, missing_message(gone))
        sentence = f"Hello, I am {settings.name}. This is how I sound."
        try:
            notes = await outside.speak_test(settings, sentence)
        except Exception as exc:
            log.warning("speaker test failed: %s", exc)
            return _said(False, f"The speaker test did not work: {exc}")
        return _said(True, " ".join([f"Said: “{sentence}”", *notes]))


def _failed(message: str) -> dict[str, Any]:
    return {"ok": False, "heard": "", "message": message}


def _said(ok: bool, message: str) -> dict[str, Any]:
    return {"ok": ok, "message": message}
