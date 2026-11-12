"""The phone channel's parts on their own: audio, the settings file, phone turns."""

from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from vision.core.bus import Bus
from vision.core.events import UserUtterance, VisionReply
from vision.core.session import Session
from vision.core.turns import TurnOrigin, brain_text
from vision.remote import audio, store
from vision.testing.fakes import FakeBrain, FakeMemory, FakeSpeaker, FakeToolHost

np = pytest.importorskip("numpy")
needs_soundfile = pytest.mark.skipif(importlib.util.find_spec("soundfile") is None, reason="needs the voice extra")


def ogg_tone(seconds: float = 1.0) -> bytes:
    import soundfile

    t = np.arange(int(48_000 * seconds)) / 48_000
    out = io.BytesIO()
    soundfile.write(out, (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32), 48_000, format="OGG", subtype="OPUS")
    return out.getvalue()


@needs_soundfile
@pytest.mark.parametrize("decoder", [audio.SoundfileDecoder(), audio.AFCONVERT, audio.FFMPEG], ids=lambda d: d.name)
def test_each_decoder_gives_16k_mono(decoder: audio.Decoder) -> None:
    if not decoder.available():
        pytest.skip(f"{decoder.name} is not on this Mac")
    sound = decoder.decode(ogg_tone())
    assert sound.dtype == np.float32 and sound.ndim == 1
    assert abs(len(sound) - 16_000) < 1_600 and float(np.abs(sound).max()) > 0.1


def test_a_missing_program_is_not_a_decoder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audio, "find_program", lambda name: None)
    assert not audio.AFCONVERT.available() and not audio.FFMPEG.available()
    with pytest.raises(audio.DecodeFailed):
        audio.FFMPEG.decode(b"x")


@needs_soundfile
def test_garbage_does_not_decode() -> None:
    with pytest.raises(audio.DecodeFailed):
        audio.SoundfileDecoder().decode(b"not audio at all")


def test_the_first_available_decoder_wins() -> None:
    class Stub:
        def __init__(self, name: str, here: bool) -> None:
            self.name, self.here = name, here

        def available(self) -> bool:
            return self.here

        def decode(self, data: bytes) -> object:
            return None

    found = audio.first_available([Stub("a", False), Stub("b", True), Stub("c", True)])  # type: ignore[list-item]
    assert found is not None and found.name == "b"
    assert audio.first_available([Stub("a", False)]) is None  # type: ignore[list-item]


@needs_soundfile
def test_a_voice_reply_is_ogg_opus_with_a_short_waveform() -> None:
    import soundfile

    sound = np.sin(np.linspace(0, 400, 24_000)).astype(np.float32)
    ogg = audio.encode_voice(sound, 24_000)
    assert ogg is not None and ogg[:4] == b"OggS"
    back, rate = soundfile.read(io.BytesIO(ogg))
    assert rate == 48_000 and abs(len(back) - 48_000) < 4_800
    shape = audio.waveform(sound)
    assert 0 < len(shape) <= 256 and max(shape) == 255


# ---------------------------------------------------------------- the file


def test_settings_round_trip_privately(tmp_path: Path) -> None:
    path = store.path_for(tmp_path)
    state = store.PhoneState(owner_id="111", owner_name="Owner", chat_id="700", phone_tools=["remember"])
    store.save(path, state)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert store.load(path) == state
    assert store.load(tmp_path / "missing.json") == store.PhoneState()


def test_a_broken_file_is_moved_aside(tmp_path: Path) -> None:
    path = store.path_for(tmp_path)
    path.write_text(json.dumps({"phone": {"owner_id": 5}}))
    assert store.load(path) == store.PhoneState()
    assert path.with_name("phone.json.broken").exists() and not path.exists()


# ---------------------------------------------------------------- phone turns


def test_the_brain_is_told_the_words_came_from_the_phone() -> None:
    text = brain_text("hello", TurnOrigin("phone"), datetime(2026, 11, 12, 9, 30, tzinfo=UTC))
    assert text.startswith("hello\n\n[Sent from the user's phone")


async def test_a_phone_turn_is_captioned_logged_and_silent_unless_asked() -> None:
    bus, memory, speaker = Bus(), FakeMemory(), FakeSpeaker()
    session = Session(bus, FakeBrain(["Fine, thanks."], delay=0), speaker, memory, FakeToolHost())
    async with bus.subscribe({UserUtterance.TYPE, VisionReply.TYPE}) as sub:
        record = await session.run_phone("How are you?", speak=False)
        said = await asyncio.wait_for(sub.__anext__(), 1)
        replied = await asyncio.wait_for(sub.__anext__(), 1)
    assert isinstance(said, UserUtterance) and said.source == "phone"
    assert isinstance(replied, VisionReply) and replied.text == "Fine, thanks."
    assert record.source == "phone" and memory.turns[-1].source == "phone"
    assert speaker.spoken == []
    await session.run_phone("Say it", speak=True)
    assert speaker.spoken == ["Fine, thanks."]


async def test_a_phone_turn_never_starts_over_another() -> None:
    session = Session(Bus(), FakeBrain(["One two three four five."], delay=0.05), FakeSpeaker(), FakeMemory(), FakeToolHost())
    first = asyncio.create_task(session.run_phone("first", speak=False))
    await asyncio.sleep(0.01)
    with pytest.raises(RuntimeError):
        await session.run_phone("second", speak=False)
    assert (await first).status == "ok"
