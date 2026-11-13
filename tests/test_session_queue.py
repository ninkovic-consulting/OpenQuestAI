"""Messages typed while the assistant answers wait and go as one turn; interrupting is on purpose."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

import pytest
from conftest import free_port, served
from settings_fakes import client
from test_protocol import open_socket
from test_session import until

from vision.app import Components, Daemon
from vision.core.bus import Bus, Subscription
from vision.core.config import Config
from vision.core.events import (
    MAX_WAITING,
    Event,
    InputInterrupt,
    InputPtt,
    InputSendNow,
    InputTakeBack,
    InputText,
    Notice,
    QueueChanged,
    StateChanged,
    UserUtterance,
    VisionReply,
)
from vision.core.interfaces import BrainEvent, Picture, ToolSpec
from vision.core import session as session_module
from vision.core.session import TOO_MANY, Session
from vision.core.turns import cut_note, waited_note
from vision.testing.fakes import (
    FakeBrain,
    FakeBudget,
    FakeHouse,
    FakeMemory,
    FakeSpeaker,
    FakeToolHost,
    FakeVoice,
)

LONG = "First sentence here. " + "and more words " * 60
"""A reply that takes about a second at 0.01 s a word: long enough to type into."""


class Pictures:
    """An image store with what the test put in it."""

    def __init__(self) -> None:
        self.kept: dict[str, Picture] = {}

    def put(self, n: int) -> str:
        image_id = f"{n:032x}"
        self.kept[image_id] = Picture(image_id, "image/png", n, n, b"png")
        return image_id

    def get(self, image_id: str) -> Picture:
        return self.kept[image_id]


class Rig:
    def __init__(
        self,
        replies: Sequence[str] = (LONG, "Got them.", "Third.", "Fourth."),
        *,
        speaker: FakeSpeaker | None = None,
        tools: FakeToolHost | None = None,
        brain: FakeBrain | None = None,
    ) -> None:
        self.bus = Bus()
        self.brain = brain or FakeBrain(list(replies), delay=0.01)
        self.speaker = speaker or FakeSpeaker()
        self.memory = FakeMemory()
        self.images = Pictures()
        self.tools = tools or FakeToolHost()
        self.session = Session(
            self.bus, self.brain, self.speaker, self.memory, self.tools, images=self.images  # type: ignore[arg-type]
        )
        self.events: Subscription = self.bus.subscribe()
        self.seen: list[Event] = []

    def drain(self) -> list[Event]:
        while not self.events._queue.empty():
            self.seen.append(self.events._queue.get_nowait())
        return self.seen

    def of(self, kind: type[Any]) -> list[Any]:
        return [e for e in self.drain() if isinstance(e, kind)]

    def typed(self, text: str, **more: Any) -> None:
        self.bus.publish(InputText(text=text, **more))

    def sent(self, n: int) -> str:
        """What the brain was given on its `n`-th turn."""
        return self.brain.sent[n][0]


@pytest.fixture
async def rig() -> AsyncIterator[Rig]:
    r = Rig()
    task = asyncio.create_task(r.session.run())
    await asyncio.sleep(0)
    yield r
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def run(r: Rig) -> asyncio.Task[None]:
    task = asyncio.create_task(r.session.run())
    await asyncio.sleep(0)
    return task


async def stop(task: asyncio.Task[None]) -> None:
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def answering(r: Rig) -> None:
    """The first turn is under way: its reply is streaming."""
    await until(lambda: r.brain.sent and r.of(StateChanged) and r.session.busy)
    await asyncio.sleep(0.05)


# ---------------------------------------------------------------- waiting


async def test_messages_typed_while_thinking_wait_and_go_as_one_turn(rig: Rig) -> None:
    rig.typed("Give me ten lines about the sea.")
    await answering(rig)
    rig.typed("Make them rhyme.")
    rig.typed("And short.")
    await until(lambda: len(rig.session.waiting) == 2)
    assert rig.brain.interrupts == 0 and not rig.memory.turns
    await until(lambda: len(rig.memory.turns) == 2)
    await rig.session.wait_idle()
    first, second = rig.memory.turns
    assert (first.status, second.status) == ("ok", "ok")
    assert second.user_text == "Make them rhyme.\n\nAnd short."
    assert rig.sent(1) == "Make them rhyme.\n\nAnd short.\n\n" + waited_note(2, "text")
    said = rig.of(UserUtterance)
    assert [u.text for u in said] == ["Give me ten lines about the sea.", "Make them rhyme.\n\nAnd short."]
    assert len(said[1].ids) == 2
    lists = [[m.preview for m in q.items] for q in rig.of(QueueChanged)]
    assert lists == [["Make them rhyme."], ["Make them rhyme.", "And short."], []]


async def test_a_message_typed_while_a_tool_runs_waits_for_the_tool() -> None:
    gate = asyncio.Event()

    async def slow(_: dict[str, Any]) -> str:
        await gate.wait()
        return "done"

    tools = FakeToolHost({"slow": (ToolSpec("slow", "Waits.", {"type": "object"}), slow)})

    class ToolBrain(FakeBrain):
        async def send(self, text: str, *, heavy: bool = False, images: Sequence[Picture] = ()) -> AsyncIterator[BrainEvent]:
            if not self.sent:
                await tools.call("slow", {})
            async for event in super().send(text, heavy=heavy, images=images):
                yield event

    r = Rig(tools=tools, brain=ToolBrain(["Ran it.", "And the next."], delay=0))
    task = await run(r)
    try:
        r.typed("run it")
        await until(lambda: tools.calls)
        r.typed("then tell me more")
        await until(lambda: r.session.waiting)
        assert not r.memory.turns
        gate.set()
        await until(lambda: len(r.memory.turns) == 2)
        assert [t.user_text for t in r.memory.turns] == ["run it", "then tell me more"]
        assert r.memory.turns[0].status == "ok"
    finally:
        await stop(task)


async def test_a_message_typed_while_speaking_waits_for_the_speech() -> None:
    speaker = FakeSpeaker(delay=0.2)
    r = Rig(["One. Two.", "Yes."], speaker=speaker)
    task = await run(r)
    try:
        r.typed("count")
        await until(lambda: speaker.spoken)
        r.typed("slower")
        await until(lambda: len(r.memory.turns) == 2)
        assert speaker.stops == 0 and speaker.spoken[:2] == ["One.", "Two."]
        assert [t.status for t in r.memory.turns] == ["ok", "ok"]
        assert r.memory.turns[1].user_text == "slower"
    finally:
        await stop(task)


async def test_one_more_than_the_cap_is_refused_with_a_plain_line(rig: Rig) -> None:
    rig.typed("start")
    await answering(rig)
    for i in range(MAX_WAITING + 1):
        rig.typed(f"extra {i}")
    await until(lambda: rig.of(Notice))
    assert [n.text for n in rig.of(Notice)] == [TOO_MANY]
    assert [m.text for m in rig.session.waiting] == [f"extra {i}" for i in range(MAX_WAITING)]


async def test_images_stay_with_their_message_in_the_combined_turn(rig: Rig) -> None:
    a, b, c = rig.images.put(10), rig.images.put(20), rig.images.put(30)
    rig.typed("start")
    await answering(rig)
    rig.typed("this one", images=[a, b])
    rig.typed("", images=[c])
    rig.typed("which is bigger?")
    await until(lambda: len(rig.memory.turns) == 2)
    turn = rig.memory.turns[1]
    assert turn.user_text == "this one\n\nwhich is bigger?"
    assert [i.width for i in turn.images] == [10, 20, 30]
    assert [p.id for p in rig.brain.images[1]] == [a, b, c]
    said = rig.of(UserUtterance)[1]
    assert [i.id for i in said.images] == [a, b, c]
    assert rig.of(QueueChanged)[1].items[1].images == 1


async def test_a_waiting_message_can_be_taken_back(rig: Rig) -> None:
    rig.typed("start")
    await answering(rig)
    rig.typed("never mind this", id="m1")
    rig.typed("keep this", id="m2")
    await until(lambda: len(rig.session.waiting) == 2)
    rig.bus.publish(InputTakeBack(id="m1"))
    await until(lambda: len(rig.session.waiting) == 1)
    await until(lambda: len(rig.memory.turns) == 2)
    assert rig.memory.turns[1].user_text == "keep this"
    assert rig.of(UserUtterance)[1].ids == ["m2"]
    assert rig.session.take_back("m2") is False  # already sent


async def test_a_yes_typed_while_a_request_waits_answers_it_and_never_waits() -> None:
    class Asking(FakeToolHost):
        def __init__(self) -> None:
            super().__init__()
            self.answered: list[str] = []

        @property
        def waiting(self) -> bool:
            return True

        def answer(self, text: str) -> bool:
            if text.strip().lower() in ("yes", "no"):
                self.answered.append(text)
                return True
            return False

    tools = Asking()
    r = Rig(tools=tools)
    task = await run(r)
    try:
        r.typed("do the thing")
        await answering(r)
        r.typed("yes")
        r.typed("and then this")
        await until(lambda: r.session.waiting)
        assert tools.answered == ["yes"]
        assert [m.text for m in r.session.waiting] == ["and then this"]  # not an answer: it waits
        assert r.brain.interrupts == 0
    finally:
        await stop(task)


async def test_a_message_after_the_reply_but_before_the_turn_closes_gets_no_note(rig: Rig) -> None:
    async with rig.bus.subscribe({VisionReply.TYPE}) as replies:
        rig.typed("hello")
        await asyncio.wait_for(replies.__anext__(), 10)
    rig.typed("and again")  # the turn is still writing its log
    await until(lambda: len(rig.memory.turns) == 2)
    assert rig.sent(1) == "and again"


# ---------------------------------------------------------------- interrupting on purpose


async def test_escape_stops_the_reply_and_what_waits_goes_at_once(rig: Rig) -> None:
    rig.typed("long one")
    await answering(rig)
    rig.typed("actually, shorter")
    await until(lambda: rig.session.waiting)
    rig.bus.publish(InputInterrupt())
    await until(lambda: len(rig.memory.turns) == 2)
    cut, second = rig.memory.turns
    assert cut.status == "interrupted" and cut.reply.startswith("First sentence here.")
    assert second.user_text == "actually, shorter"
    replies = rig.of(VisionReply)
    assert [r.status for r in replies] == ["interrupted", "ok"]
    assert rig.sent(1) == "actually, shorter\n\n" + cut_note(cut.reply, "long one") + "\n" + waited_note(1, "text")
    assert "They heard it only up to" in rig.sent(1)


async def test_now_stops_the_reply_and_sends_with_what_already_waits(rig: Rig) -> None:
    rig.typed("long one")
    await answering(rig)
    rig.typed("first addition")
    rig.typed("stop, do this instead", now=True)
    await until(lambda: len(rig.memory.turns) == 2)
    assert rig.memory.turns[0].status == "interrupted"
    assert rig.memory.turns[1].user_text == "first addition\n\nstop, do this instead"
    assert waited_note(2, "text") in rig.sent(1) and "interrupted your last reply" in rig.sent(1)


async def test_send_now_on_a_waiting_message_takes_the_ones_ahead_and_leaves_the_rest(rig: Rig) -> None:
    rig.typed("long one")
    await answering(rig)
    for i in ("a", "b", "c"):
        rig.typed(i, id=i)
    await until(lambda: len(rig.session.waiting) == 3)
    rig.bus.publish(InputSendNow(id="b"))
    await until(lambda: len(rig.memory.turns) == 3)
    assert [t.user_text for t in rig.memory.turns] == ["long one", "a\n\nb", "c"]
    assert rig.memory.turns[0].status == "interrupted"


async def test_a_cut_turn_with_nothing_heard_names_what_it_was_answering(rig: Rig) -> None:
    rig.brain.delay = 0.5  # still thinking
    rig.typed("what is the capital of Peru")
    await until(lambda: rig.brain.sent)
    rig.brain.delay = 0
    rig.typed("never mind", now=True)
    await until(lambda: len(rig.memory.turns) == 2)
    assert rig.memory.turns[0].reply == ""
    assert cut_note("", "what is the capital of Peru") in rig.sent(1)
    assert '"what is the capital of Peru"' in rig.sent(1)


async def test_the_note_about_a_cut_goes_with_the_next_turn_only(rig: Rig) -> None:
    rig.typed("long one")
    await answering(rig)
    rig.bus.publish(InputInterrupt())
    await until(lambda: rig.memory.turns)
    rig.typed("next")
    await until(lambda: len(rig.memory.turns) == 2)
    rig.typed("and after")
    await until(lambda: len(rig.memory.turns) == 3)
    assert "interrupted" in rig.sent(1) and rig.sent(2) == "and after"


# ---------------------------------------------------------------- voice


async def test_spoken_words_go_alone_and_at_once_and_what_waits_follows(rig: Rig) -> None:
    rig.typed("long one")
    await answering(rig)
    rig.typed("typed later")
    await until(lambda: rig.session.waiting)
    rig.bus.publish(UserUtterance(text="What about tomorrow?", source="voice"))  # the name over the reply
    await until(lambda: len(rig.memory.turns) == 3)
    assert [(t.source, t.user_text) for t in rig.memory.turns] == [
        ("text", "long one"),
        ("voice", "What about tomorrow?"),
        ("text", "typed later"),
    ]
    assert rig.memory.turns[0].status == "interrupted"
    assert "interrupted your last reply" in rig.sent(1)


async def test_push_to_talk_holds_what_waits_for_the_words_said_under_it(rig: Rig) -> None:
    rig.typed("long one")
    await answering(rig)
    rig.typed("typed later")
    await until(lambda: rig.session.waiting)
    rig.bus.publish(InputPtt(down=True))
    await until(lambda: rig.memory.turns)
    await asyncio.sleep(0.1)
    assert len(rig.memory.turns) == 1 and rig.session.waiting  # held, not sent
    rig.bus.publish(InputPtt(down=False))
    rig.bus.publish(UserUtterance(text="spoken", source="voice"))
    await until(lambda: len(rig.memory.turns) == 3)
    assert [t.user_text for t in rig.memory.turns] == ["long one", "spoken", "typed later"]


async def test_push_to_talk_with_nothing_said_lets_what_waits_go(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_module, "PTT_GRACE_S", 0.1)
    rig.typed("long one")
    await answering(rig)
    rig.typed("typed later")
    await until(lambda: rig.session.waiting)
    rig.bus.publish(InputPtt(down=True))
    rig.bus.publish(InputPtt(down=False))
    await until(lambda: len(rig.memory.turns) == 2)
    assert rig.memory.turns[1].user_text == "typed later"


# ---------------------------------------------------------------- the others wait


async def test_phone_jobs_and_automations_wait_for_the_owners_waiting_words(rig: Rig) -> None:
    rig.typed("long one")
    await answering(rig)
    rig.typed("mine first")
    await until(lambda: rig.session.waiting)
    with pytest.raises(RuntimeError):
        await rig.session.run_phone("from the phone", speak=False)
    with pytest.raises(RuntimeError):
        await rig.session.run_job("a job ended", speak=False)
    with pytest.raises(RuntimeError):
        await rig.session.run_automation("stretch", automation_id="a1", name="Stretch", speak=False)

    async def when_idle(start: Any) -> None:  # how the phone, the reporter and the scheduler wait
        while True:
            while rig.session.busy:
                await asyncio.sleep(0.01)
            try:
                await start()
                return
            except RuntimeError:
                continue

    await asyncio.gather(
        when_idle(lambda: rig.session.run_phone("from the phone", speak=False, waited=2, ids=["p1", "p2"])),
        when_idle(lambda: rig.session.run_job("a job ended", speak=False)),
    )
    sources = [t.source for t in rig.memory.turns]
    assert sources[:2] == ["text", "text"] and sorted(sources[2:]) == ["job", "phone"]
    assert rig.memory.turns[1].user_text == "mine first"


async def test_typing_during_a_phone_turn_waits_behind_it(rig: Rig) -> None:
    phone = asyncio.create_task(rig.session.run_phone("phone question", speak=False))
    await answering(rig)
    rig.typed("typed meanwhile")
    await phone
    await until(lambda: len(rig.memory.turns) == 2)
    assert [(t.source, t.user_text) for t in rig.memory.turns] == [
        ("phone", "phone question"),
        ("text", "typed meanwhile"),
    ]


def test_several_phone_messages_are_told_apart_from_the_windows() -> None:
    assert waited_note(1, "phone") == ""
    assert "one after another while you were busy" in waited_note(3, "phone")
    assert "while you were replying" in waited_note(1, "text")


# ---------------------------------------------------------------- every window


def slow_components(bus: Bus) -> Components:
    return Components(
        brain=FakeBrain(["word " * 150, "Both."], delay=0.01),
        tools=FakeToolHost(),
        memory=FakeMemory(),
        budget=FakeBudget(),
        voice=FakeVoice(),
        house=FakeHouse(),
    )


@pytest.fixture
async def slow_daemon(config: Config) -> AsyncIterator[Daemon]:
    async with served(Daemon(config, port=free_port(), components=slow_components)) as d:
        yield d


async def until_event(ws: Any, kind: str, timeout: float = 10) -> dict[str, Any]:
    async with asyncio.timeout(timeout):
        while True:
            event = json.loads(await ws.recv())
            if event["type"] == kind:
                return event["data"]


async def test_what_waits_survives_a_reload_and_every_window_sees_it(slow_daemon: Daemon) -> None:
    daemon = slow_daemon
    ws = await open_socket(daemon)
    try:
        await ws.send(InputText(text="a long answer please").to_json())
        await until_event(ws, "vision.delta")
        await ws.send(InputText(text="and this", id="mine-1").to_json())
        listed = await until_event(ws, "queue.changed")
        assert [(m["id"], m["preview"], m["source"]) for m in listed["items"]] == [("mine-1", "and this", "text")]
    finally:
        await ws.close()  # the window reloads
    async with client(daemon) as http:
        state = (await http.get("/api/state")).json()
    assert [m["id"] for m in state["queue"]] == ["mine-1"]
    other = await open_socket(daemon)
    try:
        said = await until_event(other, "user.utterance", timeout=15)
        assert said["text"] == "and this" and said["ids"] == ["mine-1"]
        assert (await until_event(other, "queue.changed"))["items"] == []
    finally:
        await other.close()


async def test_job_reports_and_automations_also_wait_for_the_phones_messages(
    fake_daemon: Daemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert not fake_daemon.busy_after_phone()
    monkeypatch.setattr(type(fake_daemon.phone.channel), "waiting", property(lambda self: 1))
    assert fake_daemon.busy_after_phone() and not fake_daemon.busy()
