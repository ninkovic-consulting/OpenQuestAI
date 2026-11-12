"""The Vision protocol: every event, both directions, and the JSON envelope.

This module is the single source of truth for spec section 5. Every message on
the WebSocket and every message on the in-process bus is one of the classes
below. On the wire each event is wrapped in one envelope::

    {"type": "vision.delta", "ts": 1731400000.0, "data": {"text": "Hel"}}

Usage::

    ev = VisionDelta(text="Hel")
    raw = ev.to_json()             # envelope as a JSON string
    same = parse_event(raw)        # -> VisionDelta, validated

Events are immutable pydantic models. Unknown fields, unknown types and wrong
values raise `EventError`. The `ts` field is the publish time in Unix seconds;
it lives in the envelope, not in `data`.
"""

from __future__ import annotations

import json
import time
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

Direction = Literal["out", "in"]
"""`out` is daemon to window, `in` is window to daemon."""

State = Literal["idle", "listening", "transcribing", "thinking", "speaking"]
BrainName = Literal["claude", "local", "fake"]
UtteranceSource = Literal["voice", "text"]
TurnSource = Literal["voice", "text", "automation"]
"""Where a turn came from: said, typed, or an automation that came due."""
AutomationChange = Literal["created", "updated", "deleted", "reloaded"]
RoomLight = Literal["dark", "idle", "active"]
GateOutcome = Literal["allow", "deny", "timeout"]
GateChoice = Literal["allow", "deny"]
NoticeLevel = Literal["info", "warn", "error"]


class EventError(ValueError):
    """Raised when a raw message is not a valid Vision event."""


class Event(BaseModel):
    """Base class of every event. Subclasses set `TYPE` and `DIRECTION`."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    TYPE: ClassVar[str]
    DIRECTION: ClassVar[Direction]

    ts: float = Field(default_factory=time.time, exclude=True)

    def data(self) -> dict[str, Any]:
        """The `data` part of the envelope, JSON-ready."""
        return self.model_dump(mode="json", by_alias=True)

    def to_envelope(self) -> dict[str, Any]:
        return {"type": self.TYPE, "ts": self.ts, "data": self.data()}

    def to_json(self) -> str:
        return json.dumps(self.to_envelope(), separators=(",", ":"))


# ---------------------------------------------------------------- daemon -> window


class StateChanged(Event):
    """Vision's conversational state.

    `brain` is which brain is answering. Publishers that do not know it (the
    voice loop) leave it `None`; the server fills in the current brain before
    sending, so the window always receives a value.
    """

    TYPE: ClassVar[str] = "state.changed"
    DIRECTION: ClassVar[Direction] = "out"
    state: State
    brain: BrainName | None = None


class BudgetUpdate(Event):
    """This month's API spend against the cap. `month` is `YYYY-MM`."""

    TYPE: ClassVar[str] = "budget"
    DIRECTION: ClassVar[Direction] = "out"
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    spent_usd: float = Field(ge=0)
    cap_usd: float = Field(ge=0)


class UserUtterance(Event):
    """What the user said or typed, once it is accepted as addressed to Vision."""

    TYPE: ClassVar[str] = "user.utterance"
    DIRECTION: ClassVar[Direction] = "out"
    text: str = Field(min_length=1)
    source: UtteranceSource


class VisionDelta(Event):
    """A streamed fragment of Vision's reply."""

    TYPE: ClassVar[str] = "vision.delta"
    DIRECTION: ClassVar[Direction] = "out"
    text: str = Field(min_length=1)


class VisionReply(Event):
    """Vision's reply, published once per turn when the turn ends.

    Every `user.utterance` is closed by exactly one `vision.reply` with the
    same turn. If the turn was interrupted, `text` is what was said so far; if
    it failed, `text` is the spoken error line.
    """

    TYPE: ClassVar[str] = "vision.reply"
    DIRECTION: ClassVar[Direction] = "out"
    text: str
    turn_id: str = Field(min_length=1)


class VoiceLevel(Event):
    """Output loudness, 0 to 1, about 30 times a second while speaking."""

    TYPE: ClassVar[str] = "voice.level"
    DIRECTION: ClassVar[Direction] = "out"
    level: float = Field(ge=0, le=1)


class RoomState(Event):
    """Lighting state of one room of the house."""

    TYPE: ClassVar[str] = "room.state"
    DIRECTION: ClassVar[Direction] = "out"
    room: str = Field(min_length=1)
    state: RoomLight


class GateRequest(Event):
    """A tool call waiting for the user's yes. `expires_at` is Unix seconds."""

    TYPE: ClassVar[str] = "gate.request"
    DIRECTION: ClassVar[Direction] = "out"
    id: str = Field(min_length=1)
    tool: str = Field(min_length=1)
    summary: str
    detail: str
    expires_at: float


class GateResolved(Event):
    """How a gate request ended."""

    TYPE: ClassVar[str] = "gate.resolved"
    DIRECTION: ClassVar[Direction] = "out"
    id: str = Field(min_length=1)
    decision: GateOutcome


class BrainFallback(Event):
    """The router switched brains. On the wire the first field is `from`."""

    TYPE: ClassVar[str] = "brain.fallback"
    DIRECTION: ClassVar[Direction] = "out"
    from_: BrainName = Field(alias="from")
    to: BrainName
    reason: str


class HouseChanged(Event):
    """The house plan changed; the window refetches `GET /api/house`."""

    TYPE: ClassVar[str] = "house.changed"
    DIRECTION: ClassVar[Direction] = "out"
    revision: int = Field(ge=0)


class AutomationChanged(Event):
    """An automation was created, changed (including its run results) or deleted.

    `automation` is the automation in the shape of `GET /api/automations`, or
    None when it was deleted. `reloaded` (with an empty `id`) means the whole
    list was replaced, after a reset or a restore; the window refetches it.
    """

    TYPE: ClassVar[str] = "automation.changed"
    DIRECTION: ClassVar[Direction] = "out"
    id: str
    change: AutomationChange
    automation: dict[str, Any] | None = None


class AutomationStarted(Event):
    """An automation's run began: its instruction is now a turn of its own."""

    TYPE: ClassVar[str] = "automation.started"
    DIRECTION: ClassVar[Direction] = "out"
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)


class AutomationFinished(Event):
    """An automation's run ended. `reply` is the start of what the assistant answered.

    `status` is `ok`, `failed`, `interrupted` (the user started a turn of
    their own) or `needed_approval` (a tool asked first and nobody answered).
    """

    TYPE: ClassVar[str] = "automation.finished"
    DIRECTION: ClassVar[Direction] = "out"
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    status: str = Field(min_length=1)
    reply: str


class Notice(Event):
    """A message for the user, shown in the window."""

    TYPE: ClassVar[str] = "notice"
    DIRECTION: ClassVar[Direction] = "out"
    level: NoticeLevel
    text: str = Field(min_length=1)


# ---------------------------------------------------------------- window -> daemon


class Hello(Event):
    """First message on every socket. Anything else first closes the socket."""

    TYPE: ClassVar[str] = "hello"
    DIRECTION: ClassVar[Direction] = "in"
    token: str


class InputText(Event):
    """Typed input."""

    TYPE: ClassVar[str] = "input.text"
    DIRECTION: ClassVar[Direction] = "in"
    text: str = Field(min_length=1, max_length=20_000)


class InputPtt(Event):
    """Push to talk (Space) pressed or released."""

    TYPE: ClassVar[str] = "input.ptt"
    DIRECTION: ClassVar[Direction] = "in"
    down: bool


class InputInterrupt(Event):
    """Stop the current reply. Also published internally by the voice loop on "Vision, stop"."""

    TYPE: ClassVar[str] = "input.interrupt"
    DIRECTION: ClassVar[Direction] = "in"


class GateDecision(Event):
    """The user's answer to a gate request."""

    TYPE: ClassVar[str] = "gate.decision"
    DIRECTION: ClassVar[Direction] = "in"
    id: str = Field(min_length=1)
    decision: GateChoice


# ---------------------------------------------------------------- registry

EVENT_TYPES: dict[str, type[Event]] = {
    cls.TYPE: cls
    for cls in (
        StateChanged,
        BudgetUpdate,
        UserUtterance,
        VisionDelta,
        VisionReply,
        VoiceLevel,
        RoomState,
        GateRequest,
        GateResolved,
        BrainFallback,
        HouseChanged,
        AutomationChanged,
        AutomationStarted,
        AutomationFinished,
        Notice,
        Hello,
        InputText,
        InputPtt,
        InputInterrupt,
        GateDecision,
    )
}
OUTBOUND_TYPES: frozenset[str] = frozenset(t for t, c in EVENT_TYPES.items() if c.DIRECTION == "out")
INBOUND_TYPES: frozenset[str] = frozenset(t for t, c in EVENT_TYPES.items() if c.DIRECTION == "in")


class _Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str
    ts: float
    data: dict[str, Any] = Field(default_factory=dict)


def parse_event(raw: str | bytes | dict[str, Any]) -> Event:
    """Parse and validate one envelope (JSON text or an already-decoded dict)."""
    try:
        obj = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
        env = _Envelope.model_validate(obj)
    except (ValueError, ValidationError) as exc:
        raise EventError(f"bad envelope: {exc}") from exc
    cls = EVENT_TYPES.get(env.type)
    if cls is None:
        raise EventError(f"unknown event type: {env.type!r}")
    try:
        return cls.model_validate({**env.data, "ts": env.ts})
    except ValidationError as exc:
        raise EventError(f"bad {env.type} data: {exc}") from exc
