"""The owner's messages: turns, commands, waiting for idle, voice notes."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from phone_fakes import CHAT, FakeDecoder, FakeEars, Rig, dm, rig, settle, voice_note

from vision.remote import words
from vision.remote.channel import MAX_VOICE_BYTES, command


@pytest.fixture
async def running() -> AsyncIterator[Rig]:
    r = rig()
    task = asyncio.create_task(r.channel.run())
    yield r
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def until(predicate: object, seconds: float = 3.0) -> None:
    for _ in range(int(seconds / 0.01)):
        if callable(predicate) and predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("timed out")


def test_commands_are_plain_words() -> None:
    assert command("status") == command("/Status") == command(" STATUS. ") == "status"
    assert command("stop!") == "stop" and command("help") == "help" and command("/start") == "start"
    assert command("stop the music") is None and command("what's my status?") is None


async def test_a_text_becomes_a_turn_and_the_reply_comes_back(running: Rig) -> None:
    r = running
    await r.channel.on_message(dm("What is on today?"))
    await until(lambda: len(r.transport.sent) == 1)
    assert r.host.turns == [("What is on today?", False)]
    assert r.transport.sent == [(CHAT, "Echo: What is on today?")]
    assert CHAT in r.transport.typing_in


async def test_speaking_on_the_mac_follows_the_setting(running: Rig) -> None:
    r = running
    r.state.speak_on_mac = True
    await r.channel.on_message(dm("Say it out loud"))
    await until(lambda: r.host.turns)
    assert r.host.turns == [("Say it out loud", True)]


async def test_turns_wait_for_idle_and_never_overlap(running: Rig) -> None:
    r = running
    r.host.is_busy = True  # someone is talking at the Mac
    r.host.turn_s = 0.05
    for text in ("one", "two", "three"):
        await r.channel.on_message(dm(text))
    await settle(10)
    assert r.host.turns == [] and r.channel.waiting >= 2
    r.host.is_busy = False
    await until(lambda: len(r.host.turns) == 3)
    assert [t for t, _ in r.host.turns] == ["one", "two", "three"]
    assert r.host.most_at_once == 1


async def test_too_many_waiting_is_said(running: Rig) -> None:
    r = running
    r.host.is_busy = True
    for i in range(7):
        await r.channel.on_message(dm(f"message {i}"))
    assert words.TOO_MANY in r.transport.texts()


async def test_status_help_and_stop(running: Rig) -> None:
    r = running
    await r.channel.on_message(dm("status"))
    await r.channel.on_message(dm("/help"))
    await r.channel.on_message(dm("stop"))
    status, help_text, stopped = r.transport.texts()
    assert "Vision is idle" in status and "$1.25 of $150.00" in status
    assert "shell commands are only ever approved at the Mac" in help_text
    assert stopped == words.NOTHING_TO_STOP
    assert r.host.turns == []


async def test_stop_interrupts_the_reply_and_drops_the_waiting(running: Rig) -> None:
    r = running
    r.host.turn_s = 5.0
    await r.channel.on_message(dm("tell me a long story"))
    await until(lambda: r.host.running == 1)
    await r.channel.on_message(dm("and another"))
    await r.channel.on_message(dm("stop"))
    await until(lambda: words.CUT_SHORT in "".join(r.transport.texts()))
    assert words.STOPPED in r.transport.texts()
    assert r.host.interrupts == 1
    await settle()
    assert [t for t, _ in r.host.turns] == ["tell me a long story"]


async def test_other_attachments_are_not_read(running: Rig) -> None:
    r = running
    r.transport.files["cdn://doc"] = b"%PDF-1.7 not a picture"
    document = voice_note().__class__("cdn://doc", "cat.png", "image/png", 22, voice=False)
    await r.channel.on_message(dm("", attachments=(document,)))
    assert r.transport.texts() == [words.ONLY_TEXT]
    assert "images" in words.ONLY_TEXT


# ---------------------------------------------------------------- voice notes


async def test_a_voice_note_is_heard_and_answered(running: Rig) -> None:
    r = running
    r.transport.files["cdn://note"] = b"OggS..."
    await r.channel.on_message(dm("", attachments=(voice_note(),)))
    await until(lambda: len(r.transport.sent) == 2)
    assert r.ears.heard == [16_000]
    assert r.transport.texts() == [words.heard("what is on today"), "Echo: what is on today"]
    assert r.transport.voices == []


async def test_a_voice_reply_when_asked(running: Rig) -> None:
    r = running
    r.state.voice_replies = True
    r.transport.files["cdn://note"] = b"OggS..."
    await r.channel.on_message(dm("", attachments=(voice_note(),)))
    await until(lambda: r.transport.voices, seconds=10)
    chat, size, seconds = r.transport.voices[0]
    assert chat == CHAT and size > 0 and seconds == pytest.approx(1.0)


async def test_text_turns_get_no_voice_reply(running: Rig) -> None:
    r = running
    r.state.voice_replies = True
    await r.channel.on_message(dm("typed"))
    await until(lambda: r.transport.sent)
    await settle()
    assert r.transport.voices == []


async def test_no_decoder_says_so() -> None:
    r = rig(decoders=[FakeDecoder(present=False), FakeDecoder("other", present=False)])
    await r.channel.on_message(dm("", attachments=(voice_note(),)))
    assert r.transport.texts() == [words.VOICE_NO_DECODER]
    assert r.ears.heard == []


async def test_no_speech_models_says_so() -> None:
    r = rig(ears=FakeEars(have_models=False))
    await r.channel.on_message(dm("", attachments=(voice_note(),)))
    assert r.transport.texts() == [words.VOICE_NO_MODELS]


async def test_a_note_too_large_is_refused_before_download() -> None:
    r = rig()
    await r.channel.on_message(dm("", attachments=(voice_note(size=MAX_VOICE_BYTES + 1),)))
    assert r.transport.texts() == [words.VOICE_TOO_LONG]


async def test_silence_and_failures_are_said_plainly() -> None:
    r = rig(ears=FakeEars(words="  "))
    r.transport.files["cdn://note"] = b"x"
    await r.channel.on_message(dm("", attachments=(voice_note(),)))
    assert r.transport.texts() == [words.VOICE_EMPTY]
    r = rig(ears=FakeEars(fail=True))
    r.transport.files["cdn://note"] = b"x"
    await r.channel.on_message(dm("", attachments=(voice_note(),)))
    assert r.transport.texts() == [words.VOICE_NOT_HEARD]
    assert r.host.turns == []
