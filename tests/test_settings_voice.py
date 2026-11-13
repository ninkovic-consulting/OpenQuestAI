"""Voice from the settings screen: devices, on and off at runtime, and the two tests.

The microphone is faked: the daemon's voice factory and the settings' outside world.
"""

from __future__ import annotations

import tomllib

import pytest
from settings_fakes import FakeOutside, client, denied, silent, use

from vision.app import Daemon
from vision.core.bus import Bus
from vision.core.config import Config
from vision.testing.fakes import FakeVoice
from vision.voice.errors import VoiceUnavailable
from vision.voice.on_disk import ModelMissing, missing_message
from vision.voice.settings import VoiceSettings


class RefusingVoice(FakeVoice):
    async def start(self) -> None:
        raise denied()


def downloaded(d: Daemon) -> dict[str, int]:
    return {repo: 1 for repo in VoiceSettings.from_config(d.config).model_repos()}


async def test_devices_are_listed_without_opening_the_microphone(daemon: Daemon) -> None:
    fake = use(daemon)
    async with client(daemon) as http:
        got = (await http.get("/api/voice/devices")).json()
        await http.get("/api/settings")
    assert got["installed"] is True
    assert got["inputs"] == [{"name": "MacBook Pro Microphone", "default": True}]
    assert got["outputs"] == [{"name": "MacBook Pro Speakers", "default": True}]
    assert got["voices"][0] == "af_heart" and len(got["voices"]) == 11
    assert "mic_test" not in fake.calls


async def test_devices_when_voice_is_not_installed(daemon: Daemon) -> None:
    fake = use(daemon, FakeOutside(installed=False))
    async with client(daemon) as http:
        got = (await http.get("/api/voice/devices")).json()
    assert got["installed"] is False and got["inputs"] == got["outputs"] == []
    assert "audio_devices" not in fake.calls


async def test_turn_voice_off_and_on(daemon: Daemon) -> None:
    use(daemon)
    async with client(daemon) as http:
        off = (await http.post("/api/voice", json={"enabled": False})).json()
        assert off["running"] is False and off["enabled"] is False
        assert isinstance(daemon.components.voice, FakeVoice)
        on = (await http.post("/api/voice", json={"enabled": True})).json()
        bad = await http.post("/api/voice", json={"enabled": "yes"})
    assert on["running"] is True and on["enabled"] is True and on["mic"] == "granted"
    assert daemon.session is not None
    assert daemon.session.speaker is daemon.components.voice.speaker
    assert bad.status_code == 400
    with daemon.config.paths.config_file.open("rb") as fh:
        assert tomllib.load(fh)["voice"]["enabled"] is True


async def test_a_denied_microphone_is_reported(
    daemon: Daemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    use(daemon)
    monkeypatch.setattr("vision.voice.make_voice", lambda config, bus: RefusingVoice())
    async with client(daemon) as http:
        got = (await http.post("/api/voice", json={"enabled": True})).json()
        again = (await http.get("/api/settings")).json()["voice"]
    assert got["running"] is False and got["mic"] == "denied"
    assert "Privacy & Security" in got["mic_detail"]
    assert again["mic"] == "denied"
    assert isinstance(daemon.components.voice, FakeVoice) and not daemon.voice_running


async def test_voice_test_needs_the_voice_parts(daemon: Daemon) -> None:
    fake = use(daemon, FakeOutside(installed=False))
    async with client(daemon) as http:
        got = (await http.post("/api/voice/test")).json()
    assert got["ok"] is False and "uv sync --extra voice" in got["message"]
    assert "mic_test" not in fake.calls


async def test_voice_test_needs_the_models(daemon: Daemon) -> None:
    fake = use(daemon)
    async with client(daemon) as http:
        got = (await http.post("/api/voice/test")).json()
    assert got["ok"] is False and "not downloaded" in got["message"]
    assert "mic_test" not in fake.calls


async def test_voice_test_hears(daemon: Daemon) -> None:
    fake = use(daemon)
    fake.cache = downloaded(daemon)
    async with client(daemon) as http:
        got = (await http.post("/api/voice/test")).json()
    assert got == {"ok": True, "heard": "testing one two", "message": "Heard: testing one two"}


async def test_voice_test_when_the_microphone_is_denied(daemon: Daemon) -> None:
    fake = use(daemon, FakeOutside(mic_error=denied()))
    fake.cache = downloaded(daemon)
    async with client(daemon) as http:
        got = (await http.post("/api/voice/test")).json()
        voice = (await http.get("/api/settings")).json()["voice"]
    assert got["ok"] is False
    assert "cannot hear the microphone" in got["message"] and "Vision" in got["message"]
    assert voice["mic"] == "denied"


async def test_voice_test_hears_nothing(daemon: Daemon) -> None:
    fake = use(daemon, FakeOutside(heard=""))
    fake.cache = downloaded(daemon)
    async with client(daemon) as http:
        got = (await http.post("/api/voice/test")).json()
    assert got["ok"] is False and "Nothing was heard" in got["message"]


class SilentVoice(FakeVoice):
    async def start(self) -> None:
        raise silent()


async def test_a_silent_microphone_is_not_called_a_permission_problem(
    daemon: Daemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    use(daemon)
    monkeypatch.setattr("vision.voice.make_voice", lambda config, bus: SilentVoice())
    async with client(daemon) as http:
        got = (await http.post("/api/voice", json={"enabled": True})).json()
    assert got["running"] is False and got["mic"] == "silent"
    assert got["mic_detail"].startswith("The microphone “Insta360 Link 2C” sends only silence.")
    assert "Choose another microphone" in got["mic_detail"]


async def test_voice_test_with_a_silent_microphone_names_the_device(daemon: Daemon) -> None:
    fake = use(daemon, FakeOutside(mic_error=silent()))
    fake.cache = downloaded(daemon)
    async with client(daemon) as http:
        got = (await http.post("/api/voice/test")).json()
        voice = (await http.get("/api/settings")).json()["voice"]
    assert got["ok"] is False and got["message"].startswith("The microphone “Insta360 Link 2C”")
    assert "cannot hear" not in got["message"]
    assert voice["mic"] == "silent"


async def test_choosing_another_microphone_after_a_failed_start_tries_again(
    daemon: Daemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    use(daemon)
    built: list[str] = []

    def make(config: Config, bus: Bus) -> FakeVoice:
        device = VoiceSettings.from_config(config).input_device
        built.append(device)
        return FakeVoice() if device == "AirPods" else SilentVoice()

    monkeypatch.setattr("vision.voice.make_voice", make)
    async with client(daemon) as http:
        failed = (await http.post("/api/voice", json={"enabled": True})).json()
        changed = (await http.patch("/api/settings", json={"voice": {"input_device": "AirPods"}})).json()
    assert failed["mic"] == "silent"
    assert built == ["", "AirPods"] and daemon.voice_running
    assert changed["settings"]["voice"]["mic"] == "granted"


async def test_speaker_test_says_a_sentence_without_the_microphone(daemon: Daemon) -> None:
    fake = use(daemon)
    fake.cache = {repo: 1 for repo in VoiceSettings.from_config(daemon.config).speech_repos()}
    async with client(daemon) as http:
        await http.post("/api/voice", json={"enabled": False})
        chosen = {"tts_voice": "bm_george", "output_device": "AirPods"}
        got = (await http.post("/api/voice/speak", json=chosen)).json()
        saved = (await http.post("/api/voice/speak")).json()
    assert got == {"ok": True, "message": "Said: “Hello, I am Vision. This is how I sound.”"}
    assert saved["ok"] is True
    (first, sentence), (second, _) = fake.spoken
    assert (first.tts_voice, first.output_device) == ("bm_george", "AirPods")
    assert (second.tts_voice, second.output_device) == ("af_heart", "")
    assert sentence == "Hello, I am Vision. This is how I sound."
    assert "mic_test" not in fake.calls and not daemon.voice_running


async def test_speaker_test_says_what_is_missing(daemon: Daemon) -> None:
    fake = use(daemon, FakeOutside(installed=False))
    async with client(daemon) as http:
        absent = (await http.post("/api/voice/speak")).json()
        fake.installed = True
        settings = VoiceSettings.from_config(daemon.config)
        fake.cache = {settings.stt_model: 1, settings.vad_model: 1}
        undownloaded = (await http.post("/api/voice/speak")).json()
        bad = await http.post("/api/voice/speak", json={"tts_voice": "nobody"})
    assert absent["ok"] is False and "uv sync --extra voice" in absent["message"]
    assert undownloaded == {
        "ok": False,
        "message": "The speech models are not downloaded (the speaking voice, the speaking voice's "
        "English tagger missing). Download them in Settings, Voice; nothing is downloaded by itself.",
    }
    assert bad.status_code == 400
    assert "speak_test" not in fake.calls


async def test_speaker_test_reports_a_fallback_and_a_failure(daemon: Daemon) -> None:
    fallback = "The speakers “AirPods” are not connected, so the system default (Mac Speakers) is used."
    fake = use(daemon, FakeOutside(speak_notes=[fallback]))
    fake.cache = {repo: 1 for repo in VoiceSettings.from_config(daemon.config).speech_repos()}
    async with client(daemon) as http:
        fell_back = (await http.post("/api/voice/speak")).json()
        fake.speak_error = VoiceUnavailable("Speech output could not load.")
        failed = (await http.post("/api/voice/speak")).json()
    assert fell_back["ok"] is True and fell_back["message"].endswith("(Mac Speakers) is used.")
    assert failed == {"ok": False, "message": "The speaker test did not work: Speech output could not load."}


class UndownloadedVoice(FakeVoice):
    async def start(self) -> None:
        raise ModelMissing(missing_message(["speech recognition", "the speaking voice"]))


async def test_voice_on_without_the_models_is_not_a_microphone_problem(
    daemon: Daemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = use(daemon)
    monkeypatch.setattr("vision.voice.make_voice", lambda config, bus: UndownloadedVoice())
    async with client(daemon) as http:
        got = (await http.post("/api/voice", json={"enabled": True})).json()
        tested = (await http.post("/api/voice/test")).json()
    assert got["enabled"] is True and got["running"] is False
    assert got["mic"] == "unknown" and got["models_downloaded"] is False
    assert got["mic_detail"].startswith("The speech models are not downloaded (speech recognition")
    assert "Privacy" not in got["mic_detail"]
    assert tested["ok"] is False and "Download them in Settings, Voice" in tested["message"]
    assert not any(call.startswith("download") for call in fake.calls)
