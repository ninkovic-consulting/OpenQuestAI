"""A job on the board: work handed to one resident, with its record of steps.

A job is plain data. The board (`vision.jobs.board`) changes it, saves it and
announces it; nothing else writes one.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, cast

from vision.core.events import JobChanged, JobStatus, JobStep

StepKind = Literal["started", "tool", "progress", "request", "finished"]
OPEN: frozenset[JobStatus] = frozenset({"queued", "working"})
"""A job that has not ended."""

TITLE_MAX = 80
BRIEF_MAX = 8000
STEP_TEXT_MAX = 300
MAX_STEPS_KEPT = 200
"""A job's record keeps its first steps and then its newest, never more than this."""
RESULT_MAX = 20_000


@dataclass(slots=True)
class Step:
    ts: float
    kind: StepKind
    text: str

    def event(self) -> JobStep:
        return JobStep(ts=self.ts, kind=self.kind, text=self.text)


@dataclass(slots=True)
class Job:
    id: str
    title: str
    brief: str
    agent: str
    room: str | None
    status: JobStatus
    asked_by: str
    """`host`, `owner` (from the window), or the id of the resident whose request it is."""
    parent: str | None
    careful: bool
    created_at: float
    via: str = ""
    """Where the host was asked for it: `text`, `voice`, `phone`, `automation`; empty
    otherwise. A job handed off from a phone turn is reported to the phone too."""
    started_at: float | None = None
    ended_at: float | None = None
    result: str = ""
    error: str = ""
    needed_approval: bool = False
    cost_usd: float = 0.0
    model: str = ""
    """The model it runs on, once it has started."""
    local: bool = False
    """It runs on the local model (offline mode, or Claude could not be used)."""
    steps: list[Step] = field(default_factory=list)

    @property
    def open(self) -> bool:
        return self.status in OPEN

    def add_step(self, step: Step) -> None:
        step.text = clip(step.text, STEP_TEXT_MAX)
        self.steps.append(step)
        if len(self.steps) > MAX_STEPS_KEPT:
            del self.steps[1]  # keep the first step, which says who started it

    def summary(self) -> dict[str, Any]:
        """The shape of `job.changed` and of each row of `GET /api/jobs`."""
        last = self.steps[-1] if self.steps else None
        return {
            "id": self.id,
            "title": self.title,
            "agent": self.agent,
            "room": self.room,
            "status": self.status,
            "asked_by": self.asked_by,
            "parent": self.parent,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "needed_approval": self.needed_approval,
            "model": self.model,
            "local": self.local,
            "last_step": asdict(last) if last else None,
        }

    def details(self) -> dict[str, Any]:
        """The shape of `GET /api/jobs/{id}`: the summary, the brief, the outcome and every step."""
        return {
            **self.summary(),
            "brief": self.brief,
            "careful": self.careful,
            "via": self.via,
            "result": self.result,
            "error": self.error,
            "cost_usd": round(self.cost_usd, 6),
            "steps": [asdict(s) for s in self.steps],
        }

    def event(self) -> JobChanged:
        data = self.summary()
        last = self.steps[-1].event() if self.steps else None
        return JobChanged(**{**data, "last_step": last})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Job:
        fields = dict(data)
        fields["steps"] = [Step(float(s["ts"]), cast(StepKind, s["kind"]), str(s["text"])) for s in data.get("steps", [])]
        return cls(**fields)


def clip(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
