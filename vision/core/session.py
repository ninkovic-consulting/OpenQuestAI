"""One conversation turn, end to end (spec section 6).

The session listens on the bus for `input.text` (typed), `user.utterance`
with `source="voice"` (from the voice loop), `input.interrupt` and
`input.ptt`. For each accepted input it:

1. publishes `user.utterance` (typed input only; voice already did) and
   `state.changed: thinking`;
2. streams the brain, publishing every fragment as `vision.delta`;
3. splits the stream into sentences and hands them to the speaker in order,
   publishing `state.changed: speaking` with the first one; the next
   sentence is handed over while the current one plays, so the speaker can
   prepare it and there is no gap between them;
4. waits for the speaker to finish, then publishes `vision.reply`, writes
   the turn to the log, and publishes `state.changed: idle`.

`input.interrupt`, `input.ptt` pressed, or a new input arriving mid-turn
interrupts the brain, stops the speaker, and closes the turn as
`interrupted`. An interrupted turn is replied to and logged with the
sentences the speaker had started, which is what the user actually heard;
this holds when the brain had already finished and only the speech was cut.

If the router falls back while the turn is thinking, `state.changed:
thinking` is published again so the window shows the brain now answering.

While a gate request is waiting (the turn in progress is blocked on the
user's yes), typed or spoken input is first offered to `ToolHost.answer`. A
short clear yes or no settles the request and starts no turn, so the waiting
turn carries on; anything else interrupts as usual.

An automation's run is a turn too (`run_automation`), with source
`automation`: no `user.utterance` is published, the brain is told which
automation is running and when, and when the automation is only shown, the
reply is not spoken. The scheduler starts one only while the session is idle;
input from the user interrupts it like any other turn.

The brain is told where it is: a few lines about the house and its agents
(`surroundings`), added to the user's message, never to the cached system
prompt, on the first turn, whenever they change, and every few turns.

A message from the paired phone is a turn too (`run_phone`), with source
`phone`: its words are published as `user.utterance` with source `phone`,
and the reply is spoken only when asked. Like an automation it starts only
while the session is idle, so turns never overlap.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from vision.core.bus import Bus
from vision.core.events import (
    BrainFallback,
    InputInterrupt,
    InputPtt,
    InputText,
    Notice,
    State,
    StateChanged,
    TurnSource,
    UserUtterance,
    UtteranceSource,
    VisionDelta,
    VisionReply,
)
from vision.core.interfaces import (
    Brain,
    BrainError,
    Memory,
    Speaker,
    TextDelta,
    ToolHost,
    TurnDone,
    TurnRecord,
    TurnStatus,
)
from vision.core.localtime import local_zone
from vision.core.sentences import SentenceSplitter
from vision.core.turns import TurnOrigin, brain_text, set_origin

log = logging.getLogger(__name__)

SayFn = Callable[[str], None]

FAILED_LINE = "Sorry, I can't reach any of my models right now."
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
    ) -> None:
        self.bus = bus
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
                BrainFallback.TYPE,
            }
        )

    @property
    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    async def run(self) -> None:
        async with self._sub as sub:
            try:
                async for event in sub:
                    match event:
                        case InputText(text=text):
                            await self._accept(text, "text")
                        case UserUtterance(text=text, source="voice"):
                            await self._accept(text, "voice")
                        case InputInterrupt() | InputPtt(down=True):
                            await self.interrupt()
                        case BrainFallback() if self.busy and self._shown == "thinking":
                            self._state("thinking")
            finally:
                await self.interrupt()

    async def _accept(self, text: str, source: UtteranceSource) -> None:
        """Use the input as the gate's answer if it is one, else start a turn with it."""
        if self.tools.waiting and self.tools.answer(text):
            return
        await self.submit(text, source)

    async def submit(self, text: str, source: UtteranceSource) -> None:
        """Start a turn, interrupting the one in progress."""
        await self.interrupt()
        if source == "text":
            self.bus.publish(UserUtterance(text=text, source="text"))
        self._task = asyncio.create_task(self._run_turn(_Turn(text, TurnOrigin(source))))

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

    async def run_phone(self, text: str, *, speak: bool) -> TurnRecord:
        """Run a message from the paired phone as a turn and wait for it to end.

        Like `run_automation`, only while the session is idle (it raises
        `RuntimeError` otherwise, before anything is published). The words go
        into the caption as `user.utterance` with source `phone`; the reply is
        spoken on the Mac only when `speak` is true.
        """
        if self.busy:
            raise RuntimeError("a turn is already running")
        self.bus.publish(UserUtterance(text=text, source="phone"))
        return await self._run_alone(_Turn(text, TurnOrigin("phone"), speak=speak))

    async def _run_alone(self, turn: _Turn) -> TurnRecord:
        """Start `turn` now (the session must be idle) and wait for its record."""
        if self.busy:
            raise RuntimeError("a turn is already running")
        task = asyncio.create_task(self._run_turn(turn))
        self._task = task
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
        """Wait for the turn in progress to finish (used by tests and shutdown)."""
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)

    # ------------------------------------------------------------ the turn

    def _state(self, state: State) -> None:
        self._shown = state
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
            self._reply(turn)
            await self._log(turn)
            raise
        finally:
            if speaking is not None and not speaking.done():
                speaking.cancel()
            self._state("idle")

    async def _stream(self, turn: _Turn, say: SayFn) -> None:
        splitter = SentenceSplitter()
        text = brain_text(turn.text, turn.origin, datetime.now(local_zone()), self._fresh_surroundings())
        try:
            async for event in self.brain.send(text, heavy=wants_heavy(turn.text)):
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
            self.bus.publish(VisionReply(text=turn.reply, turn_id=turn.turn_id))

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
        )
        try:
            await self.memory.log_turn(record)
        except Exception:
            log.exception("could not log turn %s", turn.turn_id)

