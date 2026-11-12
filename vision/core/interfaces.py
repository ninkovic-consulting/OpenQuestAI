"""The seams between Vision's parts.

Each Protocol here is implemented by one package and consumed by the core:

| Protocol   | Implemented in     | Built by                                             |
|------------|--------------------|------------------------------------------------------|
| `Brain`    | `vision/brains/`   | `vision.brains.make_brain(config, bus, tools, memory, budget)` |
| `Budget`   | `vision/brains/`   | `vision.brains.make_budget(config, bus)`             |
| `ToolHost` | `vision/gate/`     | `vision.gate.make_tool_host(config, bus, memory)`    |
| `Memory`   | `vision/memory/`   | `vision.memory.make_memory(config)`                  |
| `Voice`    | `vision/voice/`    | `vision.voice.make_voice(config, bus)`               |
| `House`    | `vision/house/`    | `vision.house.make_house(config, bus)`               |

Working fakes for every protocol live in `vision.testing.fakes`.

Threading: every async method is called on the daemon's event loop. Blocking
work (audio, SQLite, model inference) must be pushed off the loop with
`asyncio.to_thread` or similar. The bus is not thread-safe; publish from other
threads with `loop.call_soon_threadsafe(bus.publish, event)`.

Who publishes what on the bus:

- Session (core): `user.utterance` for typed input, `state.changed` for
  thinking / speaking / idle, `vision.delta`, `vision.reply`, `notice` for
  failed turns. A short yes or no while a gate request waits goes to
  `ToolHost.answer` instead of starting a turn.
- Daemon (core): `budget` once at startup, and `room.state` for the Hall
  (`active` while thinking or speaking, else `idle`) after recording it with
  `House.set_room_state`.
- Voice: `user.utterance` (source voice), `state.changed` for listening /
  transcribing (and back to idle when an utterance is dropped), `voice.level`,
  `input.interrupt` when it hears "<name>, stop", and `notice` when it runs
  degraded (for example speaking with macOS `say` because Kokoro failed).
- Brain (router): `brain.fallback`, `notice`.
- Budget: `budget` after every `record`, `notice` at the warning threshold and the cap.
- ToolHost (gate): `gate.request`, `gate.resolved`; it consumes `gate.decision`.
- House: `house.changed` after its plan changes.
- Server: forwards window events (`input.*`, `gate.decision`) onto the bus.

HTTP routes from other packages: build a FastAPI `APIRouter` and protect it
with the core's auth dependency, `vision.core.server.require_token`
(`APIRouter(dependencies=[Depends(require_token)])`). The server also applies
it to the `House.router` it mounts. The Origin check is server-wide
middleware and covers every route automatically.

The assistant's display name is `config.assistant.name`; never hardcode it in
user-facing text.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

from fastapi import APIRouter

from vision.core.events import BrainName, GateOutcome, RoomLight, UtteranceSource

# ---------------------------------------------------------------- brain events


@dataclass(frozen=True, slots=True)
class TextDelta:
    """A fragment of the reply text, in order. Never empty."""

    text: str


@dataclass(frozen=True, slots=True)
class TurnDone:
    """The reply finished. Always the last event of a successful `send`.

    `model` is the model that produced the final answer (e.g.
    `claude-haiku-5-5`, `mlx-community/Qwen3-4B-Instruct-2507-4bit`). Token counts are summed over every
    model call made for the turn, tool-loop calls included. `stop_reason` is
    the provider's final stop reason, or `"interrupted"` if `interrupt()` ended
    the turn early.
    """

    model: str
    input_tokens: int
    output_tokens: int
    stop_reason: str


BrainErrorKind = Literal[
    "rate_limit", "auth", "credits", "timeout", "offline", "unavailable", "bad_request", "internal"
]


@dataclass(frozen=True, slots=True)
class BrainError:
    """The turn could not be completed. Always the last event of a failed `send`.

    The router handles retries and fallback internally, so when the session
    sees a `BrainError` it means no brain could answer. `message` is for the
    user and the log, and must never contain secrets.
    """

    kind: BrainErrorKind
    message: str
    retryable: bool


BrainEvent = TextDelta | TurnDone | BrainError


@runtime_checkable
class Brain(Protocol):
    """Something that turns the user's words into a streamed reply.

    The brain owns the conversation history and runs its own tool loop: when
    the model asks for a tool, the brain calls the injected `ToolHost` and
    feeds the result back to the model. Tool calls are not surfaced as events.
    The brain reads the memory core into its system prompt and records token
    usage on the injected `Budget`.
    """

    @property
    def name(self) -> BrainName:
        """Which backend is answering right now: `claude` or `local` (`fake` in tests).

        For the router this changes when it falls back; it must be correct by
        the time the first event of a `send` is yielded.
        """
        ...

    async def start(self) -> None:
        """Prepare clients and load state. Called once before the first `send`."""
        ...

    def send(self, text: str, *, heavy: bool = False) -> AsyncIterator[BrainEvent]:
        """Send one user message and stream the reply.

        Yields zero or more `TextDelta`, then exactly one `TurnDone` or
        `BrainError`, then stops. `heavy=True` asks for the heavy model (the
        user asked Vision to think something through). Only one `send` runs
        at a time; the session never overlaps them.

        If the consumer stops iterating early (the session cancels the turn),
        the brain must clean up and keep its history consistent, recording
        the partial reply if it keeps one.
        """
        ...

    async def interrupt(self) -> None:
        """Stop the `send` in progress as soon as possible.

        Safe to call when nothing is running. After it, the running iterator
        ends promptly, optionally with `TurnDone(stop_reason="interrupted")`.
        """
        ...

    async def close(self) -> None:
        """Release clients and connections. Called once at shutdown."""
        ...


# ---------------------------------------------------------------- tools


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """A tool the brain may offer to the model.

    `input_schema` is a JSON Schema object (`{"type": "object", ...}`), which
    is the shape the Anthropic API and OpenAI-compatible APIs both accept.
    """

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolResult:
    """What a tool call produced. `content` is text for the model.

    A denied, timed-out or failed call is `ok=False` with a short explanation
    in `content` (e.g. "The user declined to run this command.").
    """

    ok: bool
    content: str


@runtime_checkable
class ToolHost(Protocol):
    """The tools Vision can use, with the gate in front of them.

    `call` looks up the tool's tier in `config.gate.tiers`: `free` runs at
    once, `ask` publishes `gate.request` and waits up to `config.gate.timeout_s`
    for a matching `gate.decision` (then publishes `gate.resolved`), `never`
    refuses. Every call and decision is written with `Memory.audit`.
    """

    def specs(self) -> list[ToolSpec]:
        """The tools to offer the model, in a stable order (stable for prompt caching)."""
        ...

    async def call(self, name: str, args: dict[str, Any]) -> ToolResult:
        """Run one tool call through the gate. Never raises for tool failures."""
        ...

    @property
    def waiting(self) -> bool:
        """True while an `ask` call waits for the user's answer."""
        ...

    def answer(self, text: str) -> bool:
        """Settle the oldest waiting request from a spoken or typed reply.

        Only a short, clear yes or no counts; anything else returns False. When
        it returns True the reply was used as the answer, and the session must
        not start a turn with it.
        """
        ...


# ---------------------------------------------------------------- memory

TurnStatus = Literal["ok", "interrupted", "failed"]


@dataclass(frozen=True, slots=True)
class Hit:
    """One search result from `Memory.recall`.

    `kind` is `note` (from the vault) or `turn` (from the turn log); `ref` is
    the note's path relative to the vault or the turn id; `ts` is Unix seconds.
    Higher `score` is better.
    """

    kind: Literal["note", "turn"]
    text: str
    ref: str
    ts: float
    score: float


@dataclass(frozen=True, slots=True)
class TurnRecord:
    """One exchange, as logged by the session.

    `turn_id` is created by the session and is unique. `reply` is what Vision
    said (partial if interrupted, the error line if failed). `brain` and
    `model` are empty strings when no model answered. Times are Unix seconds.
    """

    turn_id: str
    started_at: float
    ended_at: float
    source: UtteranceSource
    user_text: str
    reply: str
    status: TurnStatus
    brain: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    error: str = ""


@dataclass(frozen=True, slots=True)
class AuditRecord:
    """One tool call and the gate's decision.

    `decision` is `allow` for free tools and approved asks, `deny` for refused
    or `never` tools, `timeout` for unanswered asks. `result` is a short
    summary of the outcome (never secrets).
    """

    ts: float
    tool: str
    args: dict[str, Any]
    tier: str
    decision: GateOutcome
    result: str
    request_id: str = ""


@runtime_checkable
class Memory(Protocol):
    """Vision's long-term memory: the Markdown vault and the SQLite log.

    Storage lives under `config.paths.house` and `config.paths.log_db`.
    """

    async def start(self) -> None:
        """Create the vault (seeding starter files, never overwriting) and open the log."""
        ...

    async def close(self) -> None:
        """Flush and close the log."""
        ...

    def core(self) -> str:
        """The memory core for the system prompt: persona, library, recent notes.

        Kept within a fixed size budget. Synchronous and cheap: it may be
        called at the start of every turn, so cache it and rebuild after
        `remember`.
        """
        ...

    async def remember(self, text: str) -> None:
        """Append a note to Vision's notes."""
        ...

    async def recall(self, query: str, limit: int = 5) -> list[Hit]:
        """Search notes and past turns (full-text), best first."""
        ...

    async def log_turn(self, turn: TurnRecord) -> None:
        """Write one finished turn to the log."""
        ...

    async def audit(self, entry: AuditRecord) -> None:
        """Write one tool call and gate decision to the audit log."""
        ...

    async def history(self, limit: int = 50) -> list[TurnRecord]:
        """The most recent turns, oldest first, at most `limit`. Serves `/api/history`."""
        ...


# ---------------------------------------------------------------- voice


@runtime_checkable
class Speaker(Protocol):
    """Speaks Vision's reply one sentence at a time."""

    async def say(self, sentence: str) -> None:
        """Speak one sentence and return when it has finished playing.

        Returns early (without raising) if `stop()` is called meanwhile. So the
        next sentence can be prepared while one plays, the session calls `say`
        for sentence n+1 while the call for sentence n is still running (never
        more than two at once); the speaker must play them in call order. The
        speaker publishes `voice.level` while audio plays.
        """
        ...

    async def stop(self) -> None:
        """Stop speaking at once and drop anything queued. Safe when silent."""
        ...


@runtime_checkable
class Voice(Protocol):
    """The microphone loop and the speaker, as one unit.

    While running, the voice loop listens, decides what is addressed to Vision
    (wake phrase, push to talk via `input.ptt`, or the follow-up window after
    a `vision.reply`) and publishes `user.utterance` with `source="voice"`.
    While Vision speaks it only listens for the stop phrases, publishing
    `input.interrupt` when it hears one, and ignores its own voice.
    """

    @property
    def speaker(self) -> Speaker:
        """The speaker the session uses for replies."""
        ...

    async def start(self) -> None:
        """Load models and open audio devices.

        Raise if voice cannot run (missing models, no microphone permission);
        the daemon then continues text-only and shows the error as a notice.
        """
        ...

    async def stop(self) -> None:
        """Close audio devices and stop background tasks."""
        ...


# ---------------------------------------------------------------- budget


@dataclass(frozen=True, slots=True)
class BudgetStatus:
    """This month's spend. Same fields as the `budget` event."""

    month: str
    spent_usd: float
    cap_usd: float


@runtime_checkable
class Budget(Protocol):
    """Monthly API spend, priced from `config.budget.prices`."""

    def record(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        *,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> float:
        """Add one model call's cost and return it in dollars.

        Only API calls are recorded; local models never reach the budget. A
        model missing from the price table is charged at the highest known
        rate (see `vision.core.config.ceiling_price`), never as free. Persists
        the running total under `$VISION_HOME`, rolls over when the month
        turns, and publishes a `budget` event.
        """
        ...

    def status(self) -> BudgetStatus:
        """The current month's spend and cap."""
        ...

    def exhausted(self) -> bool:
        """True when this month's spend has reached the cap."""
        ...

    def set_cap(self, cap_usd: float) -> None:
        """Change the monthly cap at once (the settings screen). Does not publish `budget`."""
        ...

    def reload(self) -> None:
        """Forget the running total and read it from disk again on next use."""
        ...



# ---------------------------------------------------------------- house


@runtime_checkable
class House(Protocol):
    """The house: rooms, residents and their layout, from `config.paths.house_file`.

    The core serves `plan()` at `GET /api/house` and mounts `router` (if any)
    under `/api/house` behind the same token and Origin checks as every other
    route. The router must not define `GET ""` or `GET "/"`, which belong to
    the plan.
    """

    async def start(self) -> None:
        """Load the house files and start watching for hand edits.

        Problems with the user's file become a `notice`, never an exception.
        """
        ...

    async def close(self) -> None:
        """Stop watching the house file."""
        ...

    def set_room_state(self, room_id: str, state: RoomLight) -> None:
        """Record a room's light for the plan. Does not publish `room.state`."""
        ...

    def plan(self) -> dict[str, Any]:
        """The JSON-ready plan the window draws the house from.

        Cheap and synchronous: called on every `GET /api/house`. After a change,
        publish `house.changed` with an increasing `revision`.
        """
        ...

    @property
    def router(self) -> APIRouter | None:
        """CRUD routes for editing the house, relative to `/api/house`, or None."""
        ...
