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
import re
import time
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

Direction = Literal["out", "in"]
"""`out` is daemon to window, `in` is window to daemon."""

State = Literal["idle", "listening", "transcribing", "thinking", "speaking"]
BrainName = Literal["claude", "local", "fake"]
UtteranceSource = Literal["voice", "text", "phone"]
TurnSource = Literal["voice", "text", "automation", "phone", "job"]
"""Where a turn came from: said, typed, an automation that came due, the paired phone, or a
resident's job that ended (the host reports it)."""
AutomationChange = Literal["created", "updated", "deleted", "reloaded"]
RoomLight = Literal["dark", "idle", "active"]
GateOutcome = Literal["allow", "deny", "timeout"]
GateChoice = Literal["allow", "deny"]
NoticeLevel = Literal["info", "warn", "error"]
JobStatus = Literal["queued", "working", "done", "failed", "cancelled"]
AgentWork = Literal["idle", "working", "waiting"]
"""What a resident is doing: nothing, a job, or a job blocked on a gate request."""
PresenceReason = Literal["idle", "locked", "asleep"]
"""Why the owner counts as away from the Mac."""
ProcedureChange = Literal["saved", "removed"]
ProposalKind = Literal["tool", "change"]
ProposalStatus = Literal["waiting", "approved", "declined"]
MadeToolChange = Literal["approved", "enabled", "disabled", "updated", "deleted", "ran"]


_IMAGE_ID = re.compile(r"^[0-9a-f]{32}$")


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


class SentImage(BaseModel):
    """An image the owner sent with a message: its id in `/api/images` and its stored size."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    width: int = Field(ge=1)
    height: int = Field(ge=1)


MAX_IMAGES = 6
"""Images per message, from the window or the phone."""


class UserUtterance(Event):
    """What the user said or typed, once it is accepted as addressed to Vision.

    `images` are the images the message carried (typed in the window or sent from the
    phone); `text` may be empty only when there are some.
    """

    TYPE: ClassVar[str] = "user.utterance"
    DIRECTION: ClassVar[Direction] = "out"
    text: str
    source: UtteranceSource
    images: list[SentImage] = Field(default_factory=list, max_length=MAX_IMAGES)

    @model_validator(mode="after")
    def _says_something(self) -> UserUtterance:
        if not self.text and not self.images:
            raise ValueError("an utterance needs words or images")
        return self


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
    """A tool call waiting for the user's yes. `expires_at` is Unix seconds.

    A request made during a resident's job names the agent (`agent` is its id,
    `agent_name` what the owner calls it) and the job; the host's own requests
    leave all three null.
    """

    TYPE: ClassVar[str] = "gate.request"
    DIRECTION: ClassVar[Direction] = "out"
    id: str = Field(min_length=1)
    tool: str = Field(min_length=1)
    summary: str
    detail: str
    expires_at: float
    agent: str | None = None
    agent_name: str | None = None
    job: str | None = None


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


class BrainMode(Event):
    """Offline mode or the local model changed. `answering` is the host's brain now;
    `local_tools` is whether the local model can call tools (null until known)."""

    TYPE: ClassVar[str] = "brain.mode"
    DIRECTION: ClassVar[Direction] = "out"
    offline: bool
    answering: BrainName
    local_backend: str
    local_model: str
    local_tools: bool | None
    local_images: bool = False
    """Whether the local model can read images (none in the catalog can yet)."""


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


class JobStep(BaseModel):
    """One line of a job's record: when, what kind (started, tool, progress, request,
    finished), and a short text."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    ts: float
    kind: str
    text: str


class JobChanged(Event):
    """A job on the board changed: queued, started, a step, waiting, ended.

    Times are Unix seconds (null until they happen). `asked_by` is `host`,
    `owner` (started from the window) or the id of the resident whose request
    it is; `parent` is that resident's job. `model` is the model it runs on (empty until
    it starts) and `local` is true when that is the local model. `last_step` is the newest step.
    """

    TYPE: ClassVar[str] = "job.changed"
    DIRECTION: ClassVar[Direction] = "out"
    id: str = Field(min_length=1)
    title: str
    agent: str = Field(min_length=1)
    room: str | None
    status: JobStatus
    asked_by: str
    parent: str | None
    created_at: float
    started_at: float | None
    ended_at: float | None
    needed_approval: bool
    model: str = ""
    local: bool = False
    last_step: JobStep | None


class AgentState(Event):
    """What a resident is doing now; `job` is the job it works on, else null."""

    TYPE: ClassVar[str] = "agent.state"
    DIRECTION: ClassVar[Direction] = "out"
    agent: str = Field(min_length=1)
    state: AgentWork
    job: str | None = None


class PresenceChanged(Event):
    """The owner came to the Mac or left it (`vision.presence`).

    `reason` says why they count as away (`idle`, `locked`, `asleep`), null while
    present. `known` is false when the Mac would not say; the owner then counts as
    present. `since` is when this state began, Unix seconds.
    """

    TYPE: ClassVar[str] = "presence"
    DIRECTION: ClassVar[Direction] = "out"
    away: bool
    known: bool
    reason: PresenceReason | None = None
    since: float
    away_after_s: float


class ProcedureChanged(Event):
    """An agent's procedure was saved or removed (`vision.procedures`).

    `owner` is the agent whose own procedure it is, or `shared` for one every
    agent sees; `name` is its file name without `.md`. The window refetches.
    """

    TYPE: ClassVar[str] = "procedure.changed"
    DIRECTION: ClassVar[Direction] = "out"
    owner: str = Field(min_length=1)
    name: str = Field(min_length=1)
    change: ProcedureChange


class ProposalChanged(Event):
    """A proposal arrived or the owner decided it (`vision.proposals`).

    `kind` is `tool` (a new tool or a new version of one) or `change` (an
    agent's persona, model or thinking level); `waiting` counts the proposals
    still waiting for the owner, for the count on the window's control.
    """

    TYPE: ClassVar[str] = "proposal.changed"
    DIRECTION: ClassVar[Direction] = "out"
    id: str = Field(min_length=1)
    kind: ProposalKind
    status: ProposalStatus
    agent: str = Field(min_length=1)
    waiting: int = Field(ge=0)


class MadeToolChanged(Event):
    """A tool an agent wrote changed: approved, enabled, disabled (by the owner or because its
    script changed on disk), given another tier, deleted, or run."""

    TYPE: ClassVar[str] = "made_tool.changed"
    DIRECTION: ClassVar[Direction] = "out"
    name: str = Field(min_length=1)
    change: MadeToolChange
    enabled: bool


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
    """Typed input, with the ids of the images uploaded for it (`POST /api/images`).

    `text` may be empty only when at least one image goes with it.
    """

    TYPE: ClassVar[str] = "input.text"
    DIRECTION: ClassVar[Direction] = "in"
    text: str = Field(default="", max_length=20_000)
    images: list[str] = Field(default_factory=list, max_length=MAX_IMAGES)

    @model_validator(mode="after")
    def _says_something(self) -> InputText:
        if not self.text and not self.images:
            raise ValueError("input.text needs text or images")
        if len(set(self.images)) != len(self.images) or not all(_IMAGE_ID.match(i) for i in self.images):
            raise ValueError("images must be distinct image ids")
        return self


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
        BrainMode,
        HouseChanged,
        AutomationChanged,
        AutomationStarted,
        AutomationFinished,
        JobChanged,
        AgentState,
        PresenceChanged,
        ProcedureChanged,
        ProposalChanged,
        MadeToolChanged,
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
