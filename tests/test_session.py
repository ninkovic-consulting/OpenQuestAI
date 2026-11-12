import asyncio
from collections.abc import AsyncIterator

import pytest

from vision.core.bus import Bus, Subscription
from vision.core.events import (
    Event,
    InputInterrupt,
    InputPtt,
    InputText,
    UserUtterance,
)
from vision.core.interfaces import BrainError
from vision.core.session import FAILED_LINE, Session, wants_heavy
from vision.testing.fakes import FakeBrain, FakeMemory, FakeSpeaker, FakeToolHost


class Rig:
    def __init__(self, brain: FakeBrain, speaker: FakeSpeaker | None = None) -> None:
        self.bus = Bus()
        self.brain = brain
        self.speaker = speaker or FakeSpeaker()
        self.memory = FakeMemory()
        self.session = Session(self.bus, brain, self.speaker, self.memory, FakeToolHost())
        self.events: Subscription = self.bus.subscribe()

    def drain(self) -> list[Event]:
        out = []
        while not self.events._queue.empty():
            out.append(self.events._queue.get_nowait())
        return out

    def names(self) -> list[str]:
        out: list[str] = []
        for e in self.drain():
            name = e.TYPE
            if name == "state.changed":
                name = f"state:{e.state}"  # type: ignore[attr-defined]
            if name == "vision.delta" and out and out[-1] == name:
                continue
            out.append(name)
        return out


@pytest.fixture
async def rig() -> AsyncIterator[Rig]:
    r = Rig(FakeBrain(["One two. Three four five six seven eight nine ten."], delay=0.01))
    task = asyncio.create_task(r.session.run())
    await asyncio.sleep(0)
    yield r
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def until(predicate, timeout: float = 5) -> None:  # type: ignore[no-untyped-def]
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)


async def test_sentences_reach_speaker_in_order(rig: Rig) -> None:
    rig.bus.publish(InputText(text="hi"))
    await until(lambda: len(rig.memory.turns) == 1)
    await rig.session.wait_idle()
    assert rig.speaker.spoken == ["One two.", "Three four five six seven eight nine ten."]
    assert rig.memory.turns[0].status == "ok"


async def test_voice_utterance_is_not_republished(rig: Rig) -> None:
    rig.bus.publish(UserUtterance(text="hello", source="voice"))
    await until(lambda: len(rig.memory.turns) == 1)
    await rig.session.wait_idle()
    names = rig.names()
    assert names.count("user.utterance") == 1
    assert rig.memory.turns[0].source == "voice"


@pytest.mark.parametrize("stopper", [InputInterrupt(), InputPtt(down=True)])
async def test_interrupt_stops_brain_and_speaker(stopper: Event) -> None:
    speaker = FakeSpeaker(delay=5)  # would speak forever
    rig = Rig(FakeBrain(["First sentence. " + "word " * 200], delay=0.01), speaker)
    task = asyncio.create_task(rig.session.run())
    try:
        rig.bus.publish(InputText(text="go"))
        await until(lambda: speaker.spoken)
        rig.bus.publish(stopper)
        await until(lambda: rig.memory.turns)
        await rig.session.wait_idle()
        assert not rig.session.busy
        assert rig.brain.interrupts == 1 and speaker.stops == 1
        assert rig.memory.turns[0].status == "interrupted"
        assert rig.names()[-2:] == ["vision.reply", "state:idle"]
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_new_input_mid_reply_interrupts_and_starts_new_turn() -> None:
    rig = Rig(FakeBrain(["a " * 300, "Second answer."], delay=0.01))
    task = asyncio.create_task(rig.session.run())
    try:
        rig.bus.publish(InputText(text="first"))
        await until(lambda: rig.brain.sent)
        await asyncio.sleep(0.05)
        rig.bus.publish(UserUtterance(text="second", source="voice"))
        await until(lambda: len(rig.memory.turns) == 2)
        await rig.session.wait_idle()
        first, second = rig.memory.turns
        assert (first.status, second.status) == ("interrupted", "ok")
        assert second.reply == "Second answer."
        replies = [e for e in rig.drain() if e.TYPE == "vision.reply"]
        assert [r.turn_id for r in replies] == [first.turn_id, second.turn_id]  # type: ignore[attr-defined]
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_brain_error_is_spoken_noticed_and_logged() -> None:
    rig = Rig(FakeBrain([BrainError("offline", "no network", True)]))
    task = asyncio.create_task(rig.session.run())
    try:
        rig.bus.publish(InputText(text="hello?"))
        await until(lambda: rig.memory.turns)
        await rig.session.wait_idle()
        [turn] = rig.memory.turns
        assert turn.status == "failed" and turn.reply == FAILED_LINE
        assert turn.error == "offline: no network"
        assert rig.speaker.spoken == [FAILED_LINE]
        assert "notice" in rig.names()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_heavy_flag_passed_to_brain(rig: Rig) -> None:
    rig.bus.publish(InputText(text="Please think this through for me"))
    await until(lambda: rig.memory.turns)
    assert rig.brain.sent == [("Please think this through for me", True)]


@pytest.mark.parametrize(
    ("text", "heavy"),
    [
        ("Think it through, please", True),
        ("think hard about the plan", True),
        ("Take your time with this", True),
        ("What do you think?", False),
        ("I think it's raining", False),
    ],
)
def test_wants_heavy(text: str, heavy: bool) -> None:
    assert wants_heavy(text) is heavy
