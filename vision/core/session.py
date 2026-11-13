"""One conversation turn, end to end (spec section 6), and what waits for the next.

The session listens on the bus for `input.text` (typed), `user.utterance`
with `source="voice"` (from the voice loop), `input.interrupt`, `input.ptt`,
`input.take_back` and `input.send_now`. For each turn it:

1. publishes `user.utterance` (typed input only; voice already did) and
   `state.changed: thinking`;
2. streams the brain, publishing every fragment as `vision.delta`;
3. splits the stream into sentences and hands them to the speaker in order,
   publishing `state.changed: speaking` with the first one; the next
   sentence is handed over while the current one plays, so the speaker can
   prepare it and there is no gap between them;
4. waits for the speaker to finish, then publishes `vision.reply`, writes
   the turn to the log, and publishes `state.changed: idle`.

A message typed while a turn runs (thinking, using tools or speaking) waits,
at most `MAX_WAITING` of them; one more is refused with a notice. The owner
can take one back (`input.take_back`). When the turn ends, however it ends,
everything that waits goes as ONE turn, in the order it was written, with
its images; the brain is told the messages came while it was replying
(`turns.waited_note`). Every window lists what waits (`queue.changed`, kept by
`waiting.WaitingBoard`), so a reload or a second window loses nothing.

Interrupting is on purpose: `input.interrupt` (Escape, a stop phrase) stops
the turn and what waits goes at once; `input.text` with `now`, or
`input.send_now` naming a waiting message, stops it and sends that message
at once with the ones ahead of it. A spoken message (`user.utterance` from
the voice loop: push to talk, or the name said over the reply) stops the turn
and goes alone, at once; typed messages that wait go right after it, so the
spoken words are not folded into words the owner can still take back.
Pressing push to talk stops the turn and holds what waits until the words
said under it arrive, or until `PTT_GRACE_S` after the release brings none.

An interrupted turn closes as `interrupted`, is replied to (`vision.reply`
with that status) and logged with the sentences the speaker had started,
which is what the user actually heard; this holds when the brain had already
finished and only the speech was cut. The next turn tells the brain what the
owner heard of it (`turns.cut_note`).

If the router falls back while the turn is thinking, `state.changed:
thinking` is published again so the window shows the brain now answering.

While a gate request is waiting (the turn in progress is blocked on the
user's yes), typed or spoken input is first offered to `ToolHost.answer`. A
short clear yes or no settles the request and starts no turn and never
waits, so the waiting turn carries on; anything else is handled as above.

An automation's run is a turn too (`run_automation`), with source
`automation`: no `user.utterance` is published, the brain is told which
automation is running and when, and when the automation is only shown, the
reply is not spoken. The scheduler starts one only while the session is idle
and nothing waits (`busy`), so the owner's waiting words always go first;
typed input waits behind it like behind any other turn.

The brain is told where it is: a few lines about the house and its agents
(`surroundings`), added to the user's message, never to the cached system
prompt, on the first turn, whenever they change, and every few turns.

A message from the paired phone is a turn too (`run_phone`), with source
`phone`: its words are published as `user.utterance` with source `phone`,
and the reply is spoken only when asked. Like an automation it starts only
while the session is idle and nothing of the window's waits, so turns never
overlap and the two lanes never share a turn. Several phone messages that
waited go as one (`waited`).

So is a job report (`run_job`), with source `job`: a resident's work ended,
and the host tells the owner in its own words. No `user.utterance`; the
reply is spoken only when asked.

Images: typed input and a phone message may carry the ids of images already
kept in the `ImageStore` (`vision.attachments`). The session loads them before
the turn starts, puts their ids and sizes on `user.utterance` and in the log,
and hands them to the brain with the words (only when there are some, so a
text turn reaches the brain exactly as before). An id the store no longer has
starts no turn: a `notice` says to attach the image again. An image sent
without words is described to the brain as the owner sending it
(`turns.brain_text`).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from vision.core.bus import Bus
from vision.core.events import (
    MAX_WAITING,
    BrainFallback,
    InputInterrupt,
    InputPtt,
    InputSendNow,
    InputTakeBack,
    InputText,
    Notice,
    SentImage,
    State,
    StateChanged,
    TurnSource,
    UserUtterance,
    VisionDelta,
    VisionReply,
)
from vision.attachments.store import ImageStore, NoSuchImage
from vision.core.interfaces import (
    Brain,
    BrainError,
    Memory,
    Picture,
    Speaker,
    TextDelta,
    ToolHost,
    TurnDone,
    TurnRecord,
    TurnStatus,
)
from vision.core.localtime import local_zone
from vision.core.sentences import SentenceSplitter
from vision.core.turns import TurnOrigin, brain_text, cut_note, set_origin
from vision.core.waiting import Waiting, WaitingBoard, joined, new_id

log = logging.getLogger(__name__)

SayFn = Callable[[str], None]

FAILED_LINE = "Sorry, I can't reach any of my models right now."
IMAGE_GONE = "An image in that message is no longer here (it was removed). Attach it again to send it."
TOO_MANY = (
    f"{MAX_WAITING} messages already wait for this reply, so that one was not sent. "
    "Take one back, or stop the reply to send them now."
)
PTT_GRACE_S = 2.0
"""After push to talk is let go with nothing heard yet, what waits holds this long for the words."""
SURROUNDINGS_EVERY = 8
"""Repeat an unchanged house summary after this many turns: the brain keeps at least
half its history when it trims, so one is always in view."""

_HEAVY = re.compile(
    r"\b(think (it|this|that|things|something) (through|over)"
    r"|think (hard|carefully|deeply)|take your time)\b",
    re.IGNORECASE,
)


def wants_heavy(text: str) -> bool:
    """True when the user asks Vision to think something through."""
    return _HEAVY.search(text) is not None


@dataclass
class _Turn:
    """Mutable state of the turn in progress."""

    text: str
    origin: TurnOrigin
    speak: bool = True
    """False for an automation that is only shown: the reply is not spoken."""
    images: tuple[Picture, ...] = ()
    waited: int = 0
    """How many messages that waited go in this turn (`turns.waited_note`)."""
    cut: str = ""
    """The note about the reply the owner cut off just before (`turns.cut_note`)."""
    turn_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    started_at: float = field(default_factory=time.time)
    parts: list[str] = field(default_factory=list)
    spoken: list[str] = field(default_factory=list)
    """Sentences the speaker has started, in order."""
    status: TurnStatus = "ok"
    brain: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    error: str = ""
    replied: bool = False
    record: TurnRecord | None = None

    @property
    def source(self) -> TurnSource:
        return self.origin.source

    @property
    def reply(self) -> str:
        return "".join(self.parts)


class Session:
    """Runs turns one at a time. Start `run()` as a task; cancel it to stop."""

    def __init__(
        self,
        bus: Bus,
        brain: Brain,
        speaker: Speaker,
        memory: Memory,
        tools: ToolHost,
        *,
        surroundings: Callable[[], str] | None = None,
        images: ImageStore | None = None,
        waiting: WaitingBoard | None = None,
    ) -> None:
        self.bus = bus
        self._images = images
        self._board = waiting or WaitingBoard(bus)
        self._waiting: list[Waiting] = []
        self._upto: str | None = None
        """`input.send_now` named this message: the next turn takes the ones up to it."""
        self._cut = ""
        """The note for the next turn about the reply the owner cut off, until a turn takes it."""
        self._replied_at = 0.0
        """When the last turn's reply was published: what was written before it was written while
        the assistant replied, what came after only waited for the turn to close."""
        self._speech = False
        """A spoken message is replacing the turn: what waits holds until it has begun."""
        self._ptt_down = False
        self._ptt_hold = False
        """Push to talk stopped the turn: what waits holds for the words said under it."""
        self._grace: asyncio.TimerHandle | None = None
        self._voice: State = "idle"
        """The voice loop's own state (published while the session is idle)."""
        self._closing = False
        self._surroundings = surroundings
        self._said_surroundings: str | None = None
        self._turns_since_surroundings = 0
        self.brain = brain
        self.speaker = speaker
        self.memory = memory
        self.tools = tools
        self._task: asyncio.Task[None] | None = None
        self._shown: State = "idle"
        # Subscribe now, so input published before `run()` starts is not lost.
        self._sub = bus.subscribe(
            {
                InputText.TYPE,
                UserUtterance.TYPE,
                InputInterrupt.TYPE,
                InputPtt.TYPE,
                InputTakeBack.TYPE,
                InputSendNow.TYPE,
                StateChanged.TYPE,
                BrainFallback.TYPE,
            }
        )

    @property
    def busy(self) -> bool:
        """A turn runs, or something waits for one: other turns (phone, jobs, automations) wait."""
        return self._running or bool(self._waiting)

    @property
    def waiting(self) -> list[Waiting]:
        """The window's messages that wait, in the order they will go."""
        return list(self._waiting)

    @property
    def _running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def _held(self) -> bool:
        return self._speech or self._ptt_hold

    async def run(self) -> None:
        async with self._sub as sub:
            try:
                async for event in sub:
                    match event:
                        case InputText(text=text, images=ids, now=now, id=message_id):
                            await self.typed(text, ids, now=now, message_id=message_id)
                        case UserUtterance(text=text, source="voice"):
                            await self.spoken(text)
                        case InputPtt(down=down):
                            await self._push_to_talk(down)
                        case InputInterrupt():
                            await self.interrupt()
                        case InputTakeBack(id=message_id):
                            self.take_back(message_id)
                        case InputSendNow(id=message_id):
                            await self.send_now(message_id)
                        case StateChanged(state=state, brain=None):
                            self._voice_state(state)
                        case BrainFallback() if self._running and self._shown == "thinking":
                            self._state("thinking")
            finally:
                self._closing = True
                self._end_grace()
                await self.interrupt()

    # ------------------------------------------------------------ what the owner sends

    async def typed(
        self, text: str, image_ids: Sequence[str] = (), *, now: bool = False, message_id: str | None = None
    ) -> None:
        """A typed message: the gate's answer if it is one, else a turn now when nothing runs
        or waits, else it waits (or, `now`, stops the turn and goes with what waits).
        An image that is gone sends nothing."""
        if not image_ids and self.tools.waiting and self.tools.answer(text):
            return
        pictures = await self.load_images(image_ids)
        if pictures is None:
            return
        message = Waiting(text, pictures, "text", message_id or new_id())
        if not (self.busy or self._held):
            self._begin([message], waited=False)
            return
        if not now and len(self._waiting) >= MAX_WAITING:
            self.bus.publish(Notice(level="warn", text=TOO_MANY))
            return
        self._waiting.append(message)
        self._show_waiting()
        if now:
            self._upto = None
            await self.interrupt()
            self._next()

    async def spoken(self, text: str) -> None:
        """Words from the voice loop: the gate's answer if they are one, else a turn at once,
        alone; what waits goes right after it."""
        if self.tools.waiting and self.tools.answer(text):
            return
        self._speech = True
        try:
            await self.interrupt()
            self._start(_Turn(text, TurnOrigin("voice")))
        finally:
            self._speech = False
            self._release_ptt()

    def take_back(self, message_id: str) -> bool:
        """Drop a waiting message before it is sent; False when it is not waiting (any more)."""
        kept = [m for m in self._waiting if m.id != message_id]
        if len(kept) == len(self._waiting):
            return False
        self._waiting = kept
        if self._upto == message_id:
            self._upto = None
        self._show_waiting()
        return True

    async def send_now(self, message_id: str) -> bool:
        """Stop the turn and send this waiting message with the ones ahead of it."""
        if all(m.id != message_id for m in self._waiting):
            return False
        self._upto = message_id
        await self.interrupt()
        self._next()
        return True

    async def _push_to_talk(self, down: bool) -> None:
        self._ptt_down = down
        if down:
            self._end_grace()
            self._ptt_hold = True
            await self.interrupt()
        elif self._ptt_hold:
            self._grace = asyncio.get_running_loop().call_later(PTT_GRACE_S, self._grace_over)

    def _grace_over(self) -> None:
        self._grace = None
        if self._voice not in ("listening", "transcribing"):
            self._release_ptt()

    def _voice_state(self, state: State) -> None:
        """The voice loop heard speech, or dropped it: after a release, a drop ends the hold."""
        self._voice = state
        if state == "idle" and self._ptt_hold and not self._ptt_down and self._grace is None:
            self._release_ptt()

    def _release_ptt(self) -> None:
        self._end_grace()
        self._ptt_hold = False
        self._next()

    def _end_grace(self) -> None:
        if self._grace is not None:
            self._grace.cancel()
            self._grace = None

    # ------------------------------------------------------------ starting turns

    def _show_waiting(self) -> None:
        self._board.show("text", self._waiting)

    def _next(self) -> None:
        """Send what waits as one turn, when nothing runs and nothing holds it."""
        if self._closing or self._running or self._held or not self._waiting:
            return
        count = len(self._waiting)
        if self._upto is not None:
            count = next((i + 1 for i, m in enumerate(self._waiting) if m.id == self._upto), count)
            self._upto = None
        batch, self._waiting = self._waiting[:count], self._waiting[count:]
        self._begin(batch, waited=any(m.at < self._replied_at for m in batch))
        self._show_waiting()  # after the turn's utterance, so a window never shows the batch nowhere

    def _begin(self, batch: Sequence[Waiting], *, waited: bool) -> None:
        """Typed messages as one turn: their words in order, their images, their ids."""
        pictures = tuple(p for m in batch for p in m.pictures)
        text = joined(batch)
        self.bus.publish(
            UserUtterance(text=text, source="text", images=_sent(pictures), ids=[m.id for m in batch])
        )
        self._start(_Turn(text, TurnOrigin("text"), images=pictures, waited=len(batch) if waited else 0))

    def _start(self, turn: _Turn) -> asyncio.Task[None]:
        """Run `turn` now; when it ends, what waits goes next. It takes the note about a cut reply."""
        turn.cut, self._cut = self._cut, ""
        task = asyncio.create_task(self._run_turn(turn))
        self._task = task
        task.add_done_callback(lambda _: self._next())
        return task

    async def load_images(self, image_ids: Sequence[str]) -> tuple[Picture, ...] | None:
        """The kept images for these ids, or None (with a notice) when one is gone."""
        if not image_ids:
            return ()
        try:
            if self._images is None:
                raise NoSuchImage(image_ids[0])
            store = self._images
            return tuple([await asyncio.to_thread(store.get, i) for i in image_ids])
        except NoSuchImage:
            self.bus.publish(Notice(level="warn", text=IMAGE_GONE))
            return None

    async def run_automation(
        self, text: str, *, automation_id: str, name: str, speak: bool
    ) -> tuple[TurnRecord, TurnOrigin]:
        """Run an automation's instruction as a turn and wait for it to end.

        Call it only while the session is idle; the scheduler waits for that.
        Returns the logged turn and its origin, whose `needed_approval` says a
        tool asked first and nobody answered.
        """
        origin = TurnOrigin("automation", automation_id, name)
        return await self._run_alone(_Turn(text, origin, speak=speak)), origin

    async def run_phone(
        self,
        text: str,
        *,
        speak: bool,
        images: Sequence[Picture] = (),
        waited: int = 0,
        ids: Sequence[str] = (),
    ) -> TurnRecord:
        """Run a message from the paired phone as a turn and wait for it to end.

        Like `run_automation`, only while the session is idle (it raises
        `RuntimeError` otherwise, before anything is published). The words and
        the images' ids go into the caption as `user.utterance` with source
        `phone`; the reply is spoken on the Mac only when `speak` is true.
        `waited` counts the phone's messages that waited and go together, `ids`
        names them.
        """
        if self.busy:
            raise RuntimeError("a turn is already running")
        pictures = tuple(images)
        self.bus.publish(UserUtterance(text=text, source="phone", images=_sent(pictures), ids=list(ids)))
        return await self._run_alone(
            _Turn(text, TurnOrigin("phone"), speak=speak, images=pictures, waited=waited)
        )

    async def run_job(self, text: str, *, speak: bool) -> TurnRecord:
        """Run a job report as a turn and wait for it to end, only while idle (like
        `run_phone`, it raises `RuntimeError` otherwise)."""
        return await self._run_alone(_Turn(text, TurnOrigin("job"), speak=speak))

    async def _run_alone(self, turn: _Turn) -> TurnRecord:
        """Start `turn` now (the session must be idle) and wait for its record."""
        if self.busy:
            raise RuntimeError("a turn is already running")
        task = self._start(turn)
        await asyncio.gather(task, return_exceptions=True)
        if turn.record is None:  # interrupted before it began
            turn.status = "interrupted"
            await self._log(turn)
        assert turn.record is not None
        return turn.record

    async def interrupt(self) -> None:
        """Stop the turn in progress, if any, and wait for it to close."""
        task = self._task
        if task is None or task.done():
            return
        await self.brain.interrupt()
        await self.speaker.stop()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def wait_idle(self) -> None:
        """Wait for the turn in progress, and the ones what waits starts, to finish (tests, shutdown)."""
        while self._task is not None and not self._task.done():
            await asyncio.gather(self._task, return_exceptions=True)

    # ------------------------------------------------------------ the turn

    def _state(self, state: State) -> None:
        self._shown = state
        self._voice = "idle"  # the voice loop shows its own states again only from here
        self.bus.publish(StateChanged(state=state, brain=self.brain.name))

    async def _run_turn(self, turn: _Turn) -> None:
        speech: asyncio.Queue[str | None] = asyncio.Queue()
        speaking: asyncio.Task[None] | None = None

        def say(sentence: str) -> None:
            nonlocal speaking
            if not turn.speak:
                return
            if speaking is None:
                self._state("speaking")
                speaking = asyncio.create_task(self._speak(speech, turn))
            speech.put_nowait(sentence)

        set_origin(turn.origin)
        self._state("thinking")
        try:
            await self._stream(turn, say)
            if turn.status == "failed":
                turn.parts = [FAILED_LINE]
                say(FAILED_LINE)
            if speaking is not None:
                speech.put_nowait(None)
                await speaking
            self._reply(turn)
            await self._log(turn)
        except asyncio.CancelledError:
            turn.status = "interrupted"
            if turn.speak:
                turn.parts = [" ".join(turn.spoken)]
            self._cut = cut_note(turn.reply, turn.text)
            self._reply(turn)
            await self._log(turn)
            raise
        finally:
            if speaking is not None and not speaking.done():
                speaking.cancel()
            self._state("idle")

    async def _stream(self, turn: _Turn, say: SayFn) -> None:
        splitter = SentenceSplitter()
        now = datetime.now(local_zone())
        text = brain_text(
            turn.text,
            turn.origin,
            now,
            self._fresh_surroundings(),
            images=len(turn.images),
            waited=turn.waited,
            cut=turn.cut,
        )
        extra = {"images": turn.images} if turn.images else {}
        try:
            async for event in self.brain.send(text, heavy=wants_heavy(turn.text), **extra):
                turn.brain = self.brain.name
                match event:
                    case TextDelta(text=text) if text:
                        turn.parts.append(text)
                        self.bus.publish(VisionDelta(text=text))
                        for sentence in splitter.feed(text):
                            say(sentence)
                    case TurnDone() as done:
                        turn.model = done.model
                        turn.input_tokens = done.input_tokens
                        turn.output_tokens = done.output_tokens
                        if done.stop_reason == "interrupted":
                            turn.status = "interrupted"
                    case BrainError() as err:
                        self._fail(turn, f"{err.kind}: {err.message}")
                        return
        except Exception as exc:  # a broken brain must not take the session down
            log.exception("brain failed")
            self._fail(turn, f"internal: {type(exc).__name__}")
            return
        for sentence in splitter.flush():
            say(sentence)

    def _fresh_surroundings(self) -> str:
        """The house summary when it changed, or every few turns so trimmed history keeps one."""
        if self._surroundings is None:
            return ""
        try:
            now = self._surroundings()
        except Exception:
            log.exception("could not describe the surroundings")
            return ""
        self._turns_since_surroundings += 1
        if now == self._said_surroundings and self._turns_since_surroundings < SURROUNDINGS_EVERY:
            return ""
        self._said_surroundings, self._turns_since_surroundings = now, 0
        return now

    def _fail(self, turn: _Turn, error: str) -> None:
        self._said_surroundings = None  # the failed turn's summary never reached the history
        turn.status = "failed"
        turn.error = error
        self.bus.publish(Notice(level="error", text=f"No brain could answer ({error})."))

    async def _speak(self, speech: asyncio.Queue[str | None], turn: _Turn) -> None:
        """Say the sentences in order, handing each over while the one before plays."""
        current: asyncio.Task[None] | None = None
        upcoming: asyncio.Task[None] | None = None
        try:
            while (sentence := await speech.get()) is not None:
                upcoming = asyncio.create_task(self._say(sentence))
                if current is not None:
                    await current
                turn.spoken.append(sentence)
                current, upcoming = upcoming, None
            if current is not None:
                await current
        finally:
            for task in (current, upcoming):
                if task is not None and not task.done():
                    task.cancel()

    async def _say(self, sentence: str) -> None:
        try:
            await self.speaker.say(sentence)
        except Exception:
            log.exception("speaker failed; continuing silently")

    def _reply(self, turn: _Turn) -> None:
        if not turn.replied:
            turn.replied = True
            self._replied_at = time.time()
            self.bus.publish(VisionReply(text=turn.reply, turn_id=turn.turn_id, status=turn.status))

    async def _log(self, turn: _Turn) -> None:
        if turn.record is not None:
            return
        record = turn.record = TurnRecord(
            turn_id=turn.turn_id,
            started_at=turn.started_at,
            ended_at=time.time(),
            source=turn.source,
            user_text=turn.text,
            reply=turn.reply,
            status=turn.status,
            brain=turn.brain,
            model=turn.model,
            input_tokens=turn.input_tokens,
            output_tokens=turn.output_tokens,
            error=turn.error,
            images=tuple(p.ref for p in turn.images),
        )
        try:
            await self.memory.log_turn(record)
        except Exception:
            log.exception("could not log turn %s", turn.turn_id)


def _sent(pictures: Sequence[Picture]) -> list[SentImage]:
    return [SentImage(id=p.id, width=p.width, height=p.height) for p in pictures]
