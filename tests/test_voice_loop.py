"""The voice loop: states, wake, stop, echo guard, push to talk, follow-up, file mode.

Model-free: speech is a tone, VAD is loudness and transcripts are scripted.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
import pytest
import soundfile

from tests.test_voice_fakes import LoudnessVad, ScriptedStt, ToneSynth, drain, run_now
from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.events import InputInterrupt, InputPtt, StateChanged, UserUtterance
from vision.core.interfaces import Voice
from vision.core.session import Session
from vision.testing.fakes import FakeBrain, FakeMemory
from vision.voice import make_voice
from vision.voice.errors import VoiceUnavailable
from vision.voice.filemode import FileSource, WavSink
from vision.voice.loop import VoiceLoop
from vision.voice.service import LocalVoice, Models
from vision.voice.settings import VoiceSettings
from vision.voice.tts import TtsSpeaker
from vision.voice.vad import SpeechStarted, Utterance

SPEECH = Utterance(np.full(16_000, 0.5, dtype=np.float32))


class Harness:
    def __init__(self, tmp_path: Path, *transcripts: str, name: str = "Vision") -> None:
        self.bus = Bus()
        self.sub = self.bus.subscribe()
        self.stt = ScriptedStt(*transcripts)
        sink = WavSink(tmp_path / "out.wav")
        sink.open()
        self.speaker = TtsSpeaker(self.bus, sink, run_now)
        self.speaker.use(ToneSynth(0.6))
        self.loop = VoiceLoop(
            self.bus,
            VoiceSettings(name=name),
            FileSource(tmp_path / "unused.wav"),
            LoudnessVad(),
            self.stt,
            self.speaker,
            run_now,
        )

    async def utter(self) -> None:
        await self.loop.on_segment(SpeechStarted())
        await self.loop.on_segment(SPEECH)

    def session(self, state: str) -> None:
        self.loop.on_event(StateChanged(state=state, brain="fake"))  # type: ignore[arg-type]

    async def events(self) -> list[object]:
        return [e for e in await drain(self.sub) if e.TYPE != "voice.level"]


def states(events: list[object]) -> list[str]:
    return [e.state for e in events if isinstance(e, StateChanged)]


def utterances(events: list[object]) -> list[str]:
    return [e.text for e in events if isinstance(e, UserUtterance)]


def interrupts(events: list[object]) -> int:
    return sum(isinstance(e, InputInterrupt) for e in events)


async def test_wake_phrase_publishes_the_utterance(tmp_path: Path) -> None:
    h = Harness(tmp_path, "Hey Vision, what's on today?")
    await h.utter()
    events = await h.events()
    assert states(events) == ["listening", "transcribing"]
    assert utterances(events) == ["What's on today?"]
    assert all(e.source == "voice" for e in events if isinstance(e, UserUtterance))


async def test_unaddressed_speech_goes_back_to_idle(tmp_path: Path) -> None:
    h = Harness(tmp_path, "I think it will rain.")
    await h.utter()
    events = await h.events()
    assert states(events) == ["listening", "transcribing", "idle"]
    assert utterances(events) == []


async def test_a_click_goes_back_to_idle_without_transcribing(tmp_path: Path) -> None:
    h = Harness(tmp_path, "never used")
    await h.loop.on_segment(SpeechStarted())
    await h.loop.on_segment(Utterance(np.zeros(0, dtype=np.float32)))
    assert states(await h.events()) == ["listening", "idle"]
    assert h.stt.heard == []


async def test_name_comes_from_config(tmp_path: Path) -> None:
    h = Harness(tmp_path, "Hey Vision, hello.", "Atlas, hello.", name="Atlas")
    await h.utter()
    await h.utter()
    assert utterances(await h.events()) == ["Hello."]


async def test_follow_up_window_opens_when_a_turn_ends(tmp_path: Path) -> None:
    h = Harness(tmp_path, "And tomorrow?")
    h.session("thinking")
    h.session("speaking")
    h.session("idle")
    await h.utter()
    assert utterances(await h.events()) == ["And tomorrow?"]


async def test_no_follow_up_without_a_turn(tmp_path: Path) -> None:
    h = Harness(tmp_path, "And tomorrow?")
    await h.utter()
    assert utterances(await h.events()) == []


async def test_voice_states_never_paint_over_the_session(tmp_path: Path) -> None:
    h = Harness(tmp_path, "Hey Vision, and the weather?")
    h.session("thinking")
    await h.utter()
    events = await h.events()
    assert states(events) == []
    assert utterances(events) == ["And the weather?"]


async def test_a_chime_marks_the_start_of_thinking(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    h.session("thinking")
    h.session("thinking")
    await asyncio.sleep(0.3)
    audio, rate = soundfile.read(tmp_path / "out.wav")
    sounding = np.count_nonzero(np.abs(audio) > 0.001) / rate
    assert 0.1 < sounding < 0.2  # one chime, not two


async def test_stop_phrase_while_speaking_interrupts(tmp_path: Path) -> None:
    h = Harness(tmp_path, "Vision, stop.")
    h.session("speaking")
    await h.utter()
    events = await h.events()
    assert interrupts(events) == 1
    assert utterances(events) == []
    assert states(events) == []


async def test_other_speech_while_speaking_is_ignored(tmp_path: Path) -> None:
    h = Harness(tmp_path, "Hey Vision, what about tomorrow?")
    h.session("speaking")
    await h.utter()
    events = await h.events()
    assert interrupts(events) == 0
    assert utterances(events) == []


async def test_echo_of_its_own_sentence_is_discarded(tmp_path: Path) -> None:
    h = Harness(tmp_path, "you can say stop at any time")
    h.session("speaking")
    saying = asyncio.create_task(h.speaker.say("You can say stop at any time."))
    await asyncio.sleep(0.05)
    await h.utter()
    await saying
    events = await h.events()
    assert interrupts(events) == 0
    assert utterances(events) == []


async def test_stop_mixed_with_echo_still_interrupts(tmp_path: Path) -> None:
    h = Harness(tmp_path, "the front door is locked stop")
    h.session("speaking")
    saying = asyncio.create_task(h.speaker.say("The front door is locked."))
    await asyncio.sleep(0.05)
    await h.utter()
    await saying
    assert interrupts(await h.events()) == 1


async def test_echo_tail_after_the_reply_is_not_a_follow_up(tmp_path: Path) -> None:
    h = Harness(tmp_path, "the front door is locked")
    h.session("speaking")
    await h.speaker.say("The front door is locked.")
    h.session("idle")  # follow-up window is open, but the room still echoes
    await h.utter()
    assert utterances(await h.events()) == []


async def test_push_to_talk_interrupts_and_makes_speech_count(tmp_path: Path) -> None:
    h = Harness(tmp_path, "What about tomorrow?")
    h.session("speaking")
    h.loop.on_event(InputPtt(down=True))
    await h.loop.on_segment(SpeechStarted())
    h.session("idle")
    await h.loop.on_segment(SPEECH)
    h.loop.on_event(InputPtt(down=False))
    events = await h.events()
    assert interrupts(events) == 1
    assert utterances(events) == ["what about tomorrow"]


async def test_push_to_talk_when_idle_does_not_interrupt(tmp_path: Path) -> None:
    h = Harness(tmp_path, "Lights on.")
    h.loop.on_event(InputPtt(down=True))
    await h.utter()
    h.loop.on_event(InputPtt(down=False))
    events = await h.events()
    assert interrupts(events) == 0
    assert utterances(events) == ["Lights on."]


# ---------------------------------------------------------------- the whole voice


def tone_wav(path: Path, plan: list[tuple[str, float]]) -> Path:
    """A 16 kHz WAV: ("speech", s) is a loud tone, ("quiet", s) is silence."""
    parts = []
    for kind, seconds in plan:
        n = int(seconds * 16_000)
        t = np.arange(n) / 16_000
        parts.append(0.5 * np.sin(2 * np.pi * 300 * t) if kind == "speech" else np.zeros(n))
    soundfile.write(path, np.concatenate(parts).astype(np.float32), 16_000)
    return path


def file_voice(tmp_path: Path, plan: list[tuple[str, float]], stt: ScriptedStt, pace: float) -> LocalVoice:
    bus = Bus()
    return LocalVoice(
        bus,
        VoiceSettings(name="Vision"),
        source=FileSource(tone_wav(tmp_path / "in.wav", plan), pace=pace),
        sink=WavSink(tmp_path / "out.wav", pace=pace),
        models=lambda: Models(LoudnessVad(), stt, ToneSynth(0.5)),
    )


async def test_file_mode_conversation_with_the_fake_brain(tmp_path: Path) -> None:
    reply = " ".join(f"Sentence number {i} is here." for i in range(8))
    stt = ScriptedStt("Hey Vision, tell me a story.", "Stop.")
    voice = file_voice(
        tmp_path,
        [("quiet", 0.5), ("speech", 1.0), ("quiet", 2.0), ("speech", 0.4), ("quiet", 4.0)],
        stt,
        pace=2.0,
    )
    assert isinstance(voice, Voice)
    sub = voice.bus.subscribe()
    memory = FakeMemory()
    session = Session(voice.bus, FakeBrain([reply], delay=0.001), voice.speaker, memory)
    running = asyncio.create_task(session.run())
    await voice.start()
    try:
        await asyncio.wait_for(voice.source.ended.wait(), 15)
        await session.wait_idle()
    finally:
        await voice.stop()
        running.cancel()
        await asyncio.gather(running, return_exceptions=True)

    events = await drain(sub)
    assert utterances(events) == ["Tell me a story."]
    assert interrupts(events) == 1
    assert len(memory.turns) == 1
    audio, rate = soundfile.read(tmp_path / "out.wav")
    spoken = np.count_nonzero(np.abs(audio) > 0.01) / rate
    assert 0.2 < spoken < 8 * 0.5 - 0.5  # cut off well before the whole reply


async def test_start_raises_when_voice_is_turned_off(tmp_path: Path) -> None:
    voice = file_voice(tmp_path, [("quiet", 0.1)], ScriptedStt(), pace=0)
    voice.settings = VoiceSettings(name="Vision", enabled=False)
    with pytest.raises(VoiceUnavailable, match="enabled = false"):
        await voice.start()


async def test_start_raises_a_clear_error_when_a_model_cannot_load(tmp_path: Path) -> None:
    def broken() -> Models:
        raise VoiceUnavailable("Speech recognition could not load (test).")

    voice = file_voice(tmp_path, [("quiet", 0.1)], ScriptedStt(), pace=0)
    voice._models = broken
    with pytest.raises(VoiceUnavailable, match="Speech recognition"):
        await voice.start()


def test_make_voice_does_no_io(config: Config) -> None:
    voice = make_voice(config, Bus())
    assert isinstance(voice, Voice)
    assert isinstance(voice, LocalVoice) and voice.loop is None
