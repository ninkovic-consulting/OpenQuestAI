"""Voice from the settings screen: devices, on and off at runtime, and the microphone test.

The microphone is faked: the daemon's voice factory and the settings' outside world.
"""

from __future__ import annotations

import tomllib

import pytest
from settings_fakes import FakeOutside, client, denied, use

from vision.app import Daemon
from vision.testing.fakes import FakeVoice
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
