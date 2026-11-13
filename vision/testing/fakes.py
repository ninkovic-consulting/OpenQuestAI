"""Working fakes for every protocol in `vision.core.interfaces`.

The daemon uses them when a real part is not built yet or with
`vision run --fake-brain`; tests use them to drive one part in isolation.
None of them touches the network, the disk or audio.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import Any

from fastapi import APIRouter

from vision.core.config import Config, Price, ceiling_price
from vision.core.events import BrainName, RoomLight
from vision.core.interfaces import (
    AuditRecord,
    BrainError,
    BrainEvent,
    BudgetStatus,
    Hit,
    TextDelta,
    ToolResult,
    ToolSpec,
    TurnDone,
    TurnRecord,
)
from vision.presence.reader import Reading

DEFAULT_REPLY = (
    "I am running on the fake brain. Nothing I say here costs anything. "
    "Ask me anything you like."
)


class FakeBrain:
    """Streams scripted replies word by word with a small delay.

    `replies` are used in turn, then the last one repeats. A reply that is a
    `BrainError` is yielded as the turn's failure. `sent` records every
    `(text, heavy)` it was given.
    """

    def __init__(
        self,
        replies: Sequence[str | BrainError] = (DEFAULT_REPLY,),
        *,
        delay: float = 0.02,
        name: BrainName = "fake",
        model: str = "fake-1",
    ) -> None:
        if not replies:
            raise ValueError("FakeBrain needs at least one reply")
        self._replies = list(replies)
        self._turn = 0
        self.delay = delay
        self._name: BrainName = name
        self.model = model
        self.sent: list[tuple[str, bool]] = []
        self.interrupts = 0
        self.started = False
        self.closed = False
        self._stop = asyncio.Event()

    @property
    def name(self) -> BrainName:
        return self._name

    async def start(self) -> None:
        self.started = True

    async def send(self, text: str, *, heavy: bool = False) -> AsyncIterator[BrainEvent]:
        self.sent.append((text, heavy))
        reply = self._replies[min(self._turn, len(self._replies) - 1)]
        self._turn += 1
        self._stop.clear()
        if isinstance(reply, BrainError):
            yield reply
            return
        words = reply.split(" ")
        out_tokens = 0
        for i, word in enumerate(words):
            await asyncio.sleep(self.delay)
            if self._stop.is_set():
                yield TurnDone(self.model, len(text.split()), out_tokens, "interrupted")
                return
            out_tokens += 1
            yield TextDelta(word if i == 0 else " " + word)
        yield TurnDone(self.model, len(text.split()), out_tokens, "end_turn")

    async def interrupt(self) -> None:
        self.interrupts += 1
        self._stop.set()

    async def close(self) -> None:
        self.closed = True


ToolFn = Callable[[dict[str, Any]], Awaitable[str]]


class FakeToolHost:
    """Runs the async functions it was given, with no gate. No tools by default.

    Nothing ever waits for an answer, so `waiting` is False and `answer` never
    takes the user's words.
    """

    def __init__(self, tools: dict[str, tuple[ToolSpec, ToolFn]] | None = None) -> None:
        self._tools = dict(tools or {})
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def specs(self) -> list[ToolSpec]:
        return [spec for spec, _ in self._tools.values()]

    async def call(self, name: str, args: dict[str, Any]) -> ToolResult:
        self.calls.append((name, args))
        entry = self._tools.get(name)
        if entry is None:
            return ToolResult(ok=False, content=f"Unknown tool: {name}")
        try:
            return ToolResult(ok=True, content=await entry[1](args))
        except Exception as exc:  # a fake reports failures like the real host
            return ToolResult(ok=False, content=f"{name} failed: {exc}")

    @property
    def waiting(self) -> bool:
        return False

    def answer(self, text: str) -> bool:
        return False


class FakeMemory:
    """Memory held in lists. `recall` ranks by shared words."""

    def __init__(self, core: str = "You are a calm and capable assistant.") -> None:
        self._core = core
        self.notes: list[tuple[float, str]] = []
        self.turns: list[TurnRecord] = []
        self.audits: list[AuditRecord] = []
        self.started = False

    async def start(self) -> None:
        self.started = True

    async def close(self) -> None:
        self.started = False

    def core(self) -> str:
        return self._core

    async def remember(self, text: str) -> None:
        self.notes.append((time.time(), text))

    async def recall(self, query: str, limit: int = 5) -> list[Hit]:
        words = set(query.lower().split())
        hits: list[Hit] = []
        for i, (ts, text) in enumerate(self.notes):
            score = len(words & set(text.lower().split()))
            if score:
                hits.append(Hit("note", text, f"note-{i}", ts, float(score)))
        for turn in self.turns:
            body = f"{turn.user_text}\n{turn.reply}"
            score = len(words & set(body.lower().split()))
            if score:
                hits.append(Hit("turn", body, turn.turn_id, turn.started_at, float(score)))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]

    async def log_turn(self, turn: TurnRecord) -> None:
        self.turns.append(turn)

    async def audit(self, entry: AuditRecord) -> None:
        self.audits.append(entry)

    async def history(self, limit: int = 50) -> list[TurnRecord]:
        return self.turns[-limit:] if limit > 0 else []


class FakeSpeaker:
    """A silent speaker. `say` takes `delay` seconds per sentence unless stopped."""

    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay
        self.spoken: list[str] = []
        self.stops = 0
        self._stop = asyncio.Event()

    async def say(self, sentence: str) -> None:
        self._stop.clear()
        self.spoken.append(sentence)
        if self.delay:
            try:
                await asyncio.wait_for(self._stop.wait(), self.delay)
            except TimeoutError:
                pass

    async def stop(self) -> None:
        self.stops += 1
        self._stop.set()


class FakeVoice:
    """No microphone; just a `FakeSpeaker`."""

    def __init__(self, speaker: FakeSpeaker | None = None) -> None:
        self._speaker = speaker or FakeSpeaker()
        self.running = False

    @property
    def speaker(self) -> FakeSpeaker:
        return self._speaker

    async def start(self) -> None:
        self.running = True

    async def stop(self) -> None:
        self.running = False


class FakeBudget:
    """Adds up cost from a price table in memory. Never persists or publishes.

    Like the real budget, a model missing from the table is charged at the
    highest known rate.
    """

    def __init__(
        self,
        cap_usd: float = 150.0,
        prices: dict[str, Price] | None = None,
        search_per_1k_usd: float = 10.0,
    ) -> None:
        self.cap_usd = cap_usd
        self.prices = dict(prices or {})
        self.search_per_1k_usd = search_per_1k_usd
        self.spent_usd = 0.0

    @classmethod
    def from_config(cls, config: Config) -> FakeBudget:
        return cls(config.budget.monthly_cap_usd, config.budget.prices)

    def record(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        *,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> float:
        price = self.prices.get(model) or ceiling_price(self.prices)
        cost = (
            input_tokens * price.input_per_mtok
            + output_tokens * price.output_per_mtok
            + cache_read_tokens * price.cache_read_per_mtok
            + cache_write_tokens * price.cache_write_per_mtok
        ) / 1_000_000
        self.spent_usd += cost
        return cost

    def record_searches(self, count: int) -> float:
        cost = max(count, 0) * self.search_per_1k_usd / 1000
        self.spent_usd += cost
        return cost

    def status(self) -> BudgetStatus:
        return BudgetStatus(time.strftime("%Y-%m"), round(self.spent_usd, 6), self.cap_usd)

    def exhausted(self) -> bool:
        return self.spent_usd >= self.cap_usd

    def set_cap(self, cap_usd: float) -> None:
        self.cap_usd = cap_usd

    def reload(self) -> None:
        self.spent_usd = 0.0


class FakeHouse:
    """The Hall alone, in the plan shape of spec section 4.8, with no editing routes."""

    def __init__(self, assistant: str = "Vision") -> None:
        self.assistant = assistant
        self.states: dict[str, RoomLight] = {"hall": "idle"}
        self.running = False

    async def start(self) -> None:
        self.running = True

    async def close(self) -> None:
        self.running = False

    def set_room_state(self, room_id: str, state: RoomLight) -> None:
        if room_id not in self.states:
            raise KeyError(room_id)
        self.states[room_id] = state

    def plan(self) -> dict[str, Any]:
        return {
            "revision": 0,
            "cell_m": 4.0,
            "wall_height_m": 2.6,
            "max_extra_rooms": 20,
            "max_room_folders": 8,
            "assistant": {"name": self.assistant},
            "agents": [
                {
                    "id": "host",
                    "name": self.assistant,
                    "model": "claude-haiku-5-5",
                    "heavy_model": "claude-opus-5-5",
                    "effort": "low",
                    "heavy_effort": "high",
                    "persona": "agents/host.md",
                }
            ],
            "effort_levels": {
                "claude-haiku-5-5": ["low", "medium", "high", "xhigh", "max"],
                "claude-opus-5-5": ["low", "medium", "high", "xhigh", "max"],
            },
            "rooms": [
                {
                    "id": "hall",
                    "name": "Hall",
                    "kind": "default",
                    "shape": "rect",
                    "at": [1, 1],
                    "size": [2, 2],
                    "agent": "host",
                    "model": "claude-haiku-5-5",
                    "folders": [],
                    "floor": "red-carpet",
                    "wall": "teal-panel",
                    "tools": [
                        {"id": "shell", "title": "Shell", "available": True, "built_in": True}
                    ],
                    "state": self.states["hall"],
                }
            ],
            "doors": [],
            "free_slots": [[0, 1], [0, 2], [1, 0], [2, 0], [3, 1], [3, 2], [1, 3], [2, 3]],
        }

    @property
    def router(self) -> APIRouter | None:
        return None


class FakePresenceReader:
    """`vision.presence.Reader` with the owner's idle time, lock and display set by hand;
    `None` everywhere reads as a Mac that will not say."""

    def __init__(self, idle_s: float | None = 0.0, locked: bool | None = False, asleep: bool | None = False) -> None:
        self.idle_s, self.locked, self.asleep = idle_s, locked, asleep

    def read(self) -> Reading:
        return Reading(self.idle_s, self.locked, self.asleep)
