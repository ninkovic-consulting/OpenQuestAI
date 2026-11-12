"""An automation, its run results, and the limits on both.

An automation is a name, a schedule, an instruction in plain words and
whether its result is spoken or only shown. `next_run` is when it is next
due (None when paused past its time or finished); a once-only automation
that has run is kept, `finished`, and never runs again by itself.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from vision.scheduler.schedule import Schedule

MAX_AUTOMATIONS = 50
NAME_MAX = 60
INSTRUCTION_MAX = 1000
KEEP_RESULTS = 5
REPLY_START = 200

RunStatus = Literal["ok", "failed", "interrupted", "needed_approval", "missed"]
Trigger = Literal["schedule", "catch_up", "manual"]
"""`catch_up` is a run missed while the daemon was off, made up within the grace period."""


@dataclass(slots=True)
class RunResult:
    started_at: float
    ended_at: float
    status: RunStatus
    reply: str
    """The start of the reply, at most `REPLY_START` characters."""
    trigger: Trigger

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunResult:
        return cls(
            float(data["started_at"]),
            float(data["ended_at"]),
            data["status"],
            str(data["reply"]),
            data["trigger"],
        )


@dataclass(slots=True)
class Automation:
    id: str
    name: str
    instruction: str
    schedule: Schedule
    speak: bool
    created_at: float
    updated_at: float
    anchor: float
    """Where an interval counts from: the time it was created or its schedule changed."""
    next_run: float | None
    paused: bool = False
    finished: bool = False
    results: list[RunResult] = field(default_factory=list)

    def add_result(self, result: RunResult) -> None:
        self.results = [*self.results, result][-KEEP_RESULTS:]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Automation:
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            instruction=str(data["instruction"]),
            schedule=dict(data["schedule"]),
            speak=bool(data["speak"]),
            created_at=float(data["created_at"]),
            updated_at=float(data["updated_at"]),
            anchor=float(data["anchor"]),
            next_run=None if data.get("next_run") is None else float(data["next_run"]),
            paused=bool(data.get("paused", False)),
            finished=bool(data.get("finished", False)),
            results=[RunResult.from_dict(r) for r in data.get("results", [])][-KEEP_RESULTS:],
        )


def reply_start(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= REPLY_START else text[: REPLY_START - 1].rstrip() + "…"
