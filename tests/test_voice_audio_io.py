"""The microphone and speakers over a fake `sounddevice`: fresh device lists, the wait
for sound, the silent-microphone message and the fall back to the system default."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

import numpy as np
import pytest

from vision.voice import audio_io
from vision.voice.audio_io import Microphone, SpeakerOutput, refresh_devices
from vision.voice.errors import VoiceUnavailable
from vision.voice.vad import FRAME

MAC_MIC = {"name": "MacBook Pro Microphone", "max_input_channels": 1, "max_output_channels": 0}
MAC_SPEAKERS = {"name": "MacBook Pro Speakers", "max_input_channels": 0, "max_output_channels": 2}
AIRPODS = {"name": "AirPods", "max_input_channels": 1, "max_output_channels": 2}


class FakeStream:
    def __init__(self, sd: FakeSd, **kw: Any) -> None:
        self.sd, self.kw = sd, kw
        sd.streams.append(self)
        self.closed = False

    def start(self) -> None:
        callback = self.kw["callback"]
        if "finished_callback" not in self.kw:  # an input stream: hand over what the device sends
            for chunk in self.sd.feed:
                callback(chunk.reshape(-1, 1), len(chunk), None, None)
            return
        frames = self.kw["blocksize"]
        while True:
            out = np.zeros((frames, 1), dtype=np.float32)
            try:
                callback(out, frames, None, None)
            except self.sd.CallbackStop:
                break
        self.kw["finished_callback"]()

    def close(self) -> None:
        self.closed = True


class FakeSd:
    """Enough of `sounddevice`: a device list that changes only when PortAudio initialises."""

    PortAudioError = type("PortAudioError", (Exception,), {})
    CallbackStop = type("CallbackStop", (Exception,), {})

    def __init__(self, devices: list[dict[str, Any]], feed: list[np.ndarray]) -> None:
        self.devices = devices
        self.plugged = devices
        """What is connected now; PortAudio sees it at the next initialise."""
        self.feed = feed
        self.streams: list[FakeStream] = []
        self.initialised = 0

    def _terminate(self) -> None:
        pass

    def _initialize(self) -> None:
        self.initialised += 1
        self.devices = self.plugged

    def query_devices(self, device: int | None = None, kind: str | None = None) -> Any:
        if device is not None:
            return self.devices[device]
        if kind is None:
            return self.devices
        channels = f"max_{kind}_channels"
        return next(d for d in self.devices if d[channels] > 0)

    def InputStream(self, **kw: Any) -> FakeStream:  # noqa: N802 - sounddevice's name
        return FakeStream(self, **kw)

    def OutputStream(self, **kw: Any) -> FakeStream:  # noqa: N802
        return FakeStream(self, **kw)


def chunks(*levels: float) -> list[np.ndarray]:
    return [np.full(FRAME, level, dtype=np.float32) for level in levels]


@pytest.fixture
def sd(monkeypatch: pytest.MonkeyPatch) -> FakeSd:
    fake = FakeSd([MAC_MIC, MAC_SPEAKERS], chunks(0.1))
    monkeypatch.setattr(audio_io, "_sd", lambda: fake)
    monkeypatch.delenv("VISION_APP", raising=False)
    return fake


async def test_a_device_plugged_in_after_start_opens(sd: FakeSd) -> None:
    sd.plugged = [MAC_MIC, MAC_SPEAKERS, AIRPODS]
    mic = Microphone("AirPods")
    await mic.open()
    assert mic.name == "AirPods" and sd.streams[0].kw["device"] == 2
    await mic.close()


async def test_devices_are_not_refreshed_under_an_open_stream(sd: FakeSd) -> None:
    mic = Microphone()
    await mic.open()
    assert sd.initialised == 1
    assert refresh_devices() is False and sd.initialised == 1
    await mic.close()
    assert refresh_devices() is True and sd.initialised == 2


async def test_a_slow_microphone_is_waited_for(sd: FakeSd) -> None:
    sd.feed = chunks(*[0.0] * 17, 0.2)  # about 0.54 s of zeros, like AirPods waking
    mic = Microphone()
    await mic.open()
    got = []
    async for chunk in mic.chunks():
        got.append(chunk)
        if len(got) == 18:
            break
    assert float(got[-1][0]) == pytest.approx(0.2)
    await mic.close()


async def test_a_silent_microphone_names_the_device_and_the_likely_causes(sd: FakeSd) -> None:
    sd.feed = chunks(*[0.0] * 100)  # 3.2 s of zeros
    mic = Microphone()
    with pytest.raises(VoiceUnavailable) as caught:
        await mic.open()
    message = str(caught.value)
    assert message.startswith("The microphone “MacBook Pro Microphone” sends only silence. It may be muted")
    assert message.index("Choose another microphone") < message.index("Privacy & Security")
    assert sys.executable in message
    assert sd.streams[0].closed and refresh_devices() is True


async def test_under_the_mac_app_the_message_names_the_app(
    sd: FakeSd, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VISION_APP", "Vision")
    monkeypatch.setattr(audio_io, "NO_AUDIO_GRACE_S", 0.01)
    sd.feed = []
    with pytest.raises(VoiceUnavailable) as caught:
        await Microphone(wait_s=0.01).open()
    message = str(caught.value)
    assert "sends no audio" in message and "check that Vision may use the microphone" in message
    assert sys.executable not in message and "terminal" not in message


async def test_a_missing_microphone_falls_back_to_the_default(sd: FakeSd) -> None:
    said: list[str] = []
    mic = Microphone("Insta360 Link 2C", on_missing=said.append)
    await mic.open()
    assert sd.streams[0].kw["device"] is None and mic.name == "MacBook Pro Microphone"
    assert said == [
        "The microphone “Insta360 Link 2C” is not connected, so the system default "
        "(MacBook Pro Microphone) is used."
    ]
    await mic.close()


async def test_speakers_follow_the_device_list_and_say_a_fallback_once(sd: FakeSd) -> None:
    said: list[str] = []
    out = SpeakerOutput("AirPods", on_missing=said.append)
    out.open()
    audio = np.full(2_000, 0.1, dtype=np.float32)
    assert await out.play(audio, 24_000) and await out.play(audio, 24_000)
    assert [s.kw["device"] for s in sd.streams] == [None, None]
    assert said == ["The speakers “AirPods” are not connected, so the system default (MacBook Pro Speakers) is used."]
    sd.plugged = [MAC_MIC, MAC_SPEAKERS, AIRPODS]
    out.open()
    assert await out.play(audio, 24_000)
    assert sd.streams[-1].kw["device"] == 2 and all(s.closed for s in sd.streams)
    assert len(said) == 1


def test_settings_list_the_devices_in_a_fresh_process(monkeypatch: pytest.MonkeyPatch) -> None:
    from vision.settings import outside

    rows = [{"name": "AirPods", "inputs": 1, "outputs": 2, "default_input": True, "default_output": False}]
    ran: list[list[str]] = []

    def run(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        ran.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(rows))

    monkeypatch.setattr(outside.subprocess, "run", run)
    monkeypatch.setattr(outside.importlib.util, "find_spec", lambda name: object())
    got = outside.MacOutside().audio_devices()
    assert ran == [[sys.executable, "-m", "vision.voice.devices"]]
    assert got == [outside.AudioDevice("AirPods", 1, 2, True, False)]


def test_the_listing_falls_back_to_this_process_when_the_child_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from vision.settings import outside
    from vision.voice import devices

    def run(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd, 15)

    sd = FakeSd([MAC_MIC, MAC_SPEAKERS], [])
    sd.default = type("Default", (), {"device": (0, 1)})()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sounddevice", sd)
    monkeypatch.setattr(outside.subprocess, "run", run)
    monkeypatch.setattr(outside.importlib.util, "find_spec", lambda name: object())
    got = outside.MacOutside().audio_devices()
    assert [d.name for d in got] == ["MacBook Pro Microphone", "MacBook Pro Speakers"]
    assert got[0].default_input and got[1].default_output
    assert devices.current()[0]["inputs"] == 1
