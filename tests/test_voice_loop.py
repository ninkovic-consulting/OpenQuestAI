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
from vision.core.events import (
    GateRequest,
    ListenMode,
    GateResolved,
    InputInterrupt,
    InputPtt,
    Notice,
    StateChanged,
    UserUtterance,
)
from vision.core.interfaces import Voice
from vision.core.session import Session
from vision.testing.fakes import FakeBrain, FakeMemory, FakeToolHost
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
    def __init__(self, tmp_path: Path, *transcripts: str, name: str = "Vision", listen: ListenMode = "wake") -> None:
        self.bus = Bus()
        self.sub = self.bus.subscribe()
        self.stt = ScriptedStt(*transcripts)
        sink = WavSink(tmp_path / "out.wav")
        sink.open()
        self.speaker = TtsSpeaker(self.bus, sink, run_now)
        self.speaker.use(ToneSynth(0.6))
        self.loop = VoiceLoop(
            self.bus,
            VoiceSettings(name=name, listen=listen),
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
    h = Harness(tmp_path, "What about tomorrow?", "Vision, um.", "Hey Vision, what about tomorrow?", listen="wake")
    h.session("speaking")
    await h.utter()  # no name
    await h.utter()  # the name with nothing after it
    h.loop.set_mode("hold")
    await h.utter()  # in hold, the name is not enough
    events = await h.events()
    assert interrupts(events) == 0
    assert utterances(events) == []


@pytest.mark.parametrize("listen", ["wake", "always"])
async def test_the_name_over_the_reply_is_the_next_message(tmp_path: Path, listen: ListenMode) -> None:
    h = Harness(tmp_path, "Hey Vision, what about tomorrow?", listen=listen)
    h.session("speaking")
    await h.utter()
    events = await h.events()
    assert utterances(events) == ["What about tomorrow?"]
    assert interrupts(events) == 0  # the session stops the reply for the new message
    assert states(events) == []


async def test_its_own_name_in_its_own_speech_never_interrupts_it(tmp_path: Path) -> None:
    h = Harness(
        tmp_path,
        "vision here the plan for today is ready",
        "I am vision and I will read it to you",
        listen="always",
    )
    h.session("speaking")
    for sentence in ("Vision here. The plan for today is ready.", "I am Vision, and I will read it to you."):
        saying = asyncio.create_task(h.speaker.say(sentence))
        await asyncio.sleep(0.05)
        await h.utter()
        await saying
    events = await h.events()
    assert utterances(events) == [] and interrupts(events) == 0


async def test_the_name_over_its_own_echo_still_gets_through(tmp_path: Path) -> None:
    h = Harness(tmp_path, "the plan for today is ready vision wait what about the bank", listen="wake")
    h.session("speaking")
    saying = asyncio.create_task(h.speaker.say("The plan for today is ready."))
    await asyncio.sleep(0.05)
    await h.utter()
    await saying
    assert utterances(await h.events()) == ["Wait what about the bank"]


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
        VoiceSettings(name="Vision", listen="wake"),
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
    brain = FakeBrain([reply], delay=0.001)
    session = Session(voice.bus, brain, voice.speaker, memory, FakeToolHost())
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


def gate_request(request_id: str = "r1") -> GateRequest:
    return GateRequest(id=request_id, tool="shell", summary="Run", detail="ls", expires_at=0.0)


async def test_bare_answer_is_passed_on_while_a_gate_request_waits(tmp_path: Path) -> None:
    h = Harness(tmp_path, "Yes.", "Yes.")
    h.session("speaking")  # a sentence was said before the tool call, then the gate waits
    h.loop.on_event(gate_request())
    await h.utter()
    assert utterances(await h.events()) == ["Yes."]
    h.loop.on_event(GateResolved(id="r1", decision="allow"))
    await h.utter()
    assert utterances(await h.events()) == []  # speaking again, nothing waits


async def test_no_answer_is_taken_while_audio_plays_during_a_gate_wait(tmp_path: Path) -> None:
    h = Harness(tmp_path, "Yes.")
    h.session("thinking")
    h.loop.on_event(gate_request())
    saying = asyncio.create_task(h.speaker.say("Shall I run it?"))
    await asyncio.sleep(0.25)  # after the thinking chime, into the sentence
    assert h.speaker.playing
    await h.utter()
    await saying
    assert utterances(await h.events()) == []


async def test_falling_back_to_say_is_a_notice(tmp_path: Path) -> None:
    voice = file_voice(tmp_path, [("quiet", 0.1)], ScriptedStt(), pace=0)
    sub = voice.bus.subscribe({Notice.TYPE})
    voice._models = lambda: Models(LoudnessVad(), ScriptedStt(), ToneSynth(0.1), "Using say.")
    await voice.start()
    try:
        notice = await asyncio.wait_for(sub.__anext__(), 2)
    finally:
        await voice.stop()
    assert isinstance(notice, Notice) and (notice.level, notice.text) == ("warn", "Using say.")


# ---------------------------------------------------------------- listening modes

LONG_SPEECH = Utterance(np.full(16_000, 0.5, dtype=np.float32), voiced_s=1.0)


async def test_always_takes_speech_without_the_name(tmp_path: Path) -> None:
    h = Harness(tmp_path, "What is on today then?", "Okay.", listen="always")
    for _ in range(2):
        await h.loop.on_segment(SpeechStarted())
        await h.loop.on_segment(LONG_SPEECH)
    assert utterances(await h.events()) == ["What is on today then?"]


async def test_always_still_ignores_its_own_echo_and_hears_stop(tmp_path: Path) -> None:
    h = Harness(tmp_path, "the front door is locked now", "Stop.", listen="always")
    h.session("speaking")
    saying = asyncio.create_task(h.speaker.say("The front door is locked now."))
    await asyncio.sleep(0.05)
    await h.loop.on_segment(SpeechStarted())
    await h.loop.on_segment(LONG_SPEECH)
    await h.loop.on_segment(SpeechStarted())
    await h.loop.on_segment(LONG_SPEECH)
    await saying
    events = await h.events()
    assert utterances(events) == []
    assert interrupts(events) == 1


async def test_hold_takes_nothing_unheld_even_while_a_gate_request_waits(tmp_path: Path) -> None:
    h = Harness(tmp_path, "Yes.", "Yes.", listen="hold")
    h.session("speaking")
    h.loop.on_event(gate_request())
    await h.utter()
    assert utterances(await h.events()) == []
    h.loop.on_event(InputPtt(down=True))
    await h.utter()
    assert utterances(await h.events()) == ["Yes."]


async def test_the_mode_changes_the_next_decision(tmp_path: Path) -> None:
    h = Harness(tmp_path, "Vision, lights on.", "Vision, lights on.", listen="hold")
    await h.loop.on_segment(SpeechStarted())
    h.loop.set_mode("wake")  # changed mid-utterance: the utterance is decided by the new mode
    await h.loop.on_segment(SPEECH)
    h.loop.set_mode("hold")
    await h.utter()
    assert utterances(await h.events()) == ["Lights on."]
