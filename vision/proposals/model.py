"""What a proposal is, who makes it, and the limits on them.

A proposal is an agent asking the owner for something it may not do alone:
a new tool (a script it wrote) or a new version of one, or a change to its own
persona, model or thinking level. It records everything the owner decides on
(the exact script and its hash, or the value before and after), so the card in
the window shows what will happen and nothing else can happen on approval.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

Kind = Literal["tool", "change"]
Status = Literal["waiting", "approved", "declined"]
Who = Literal["author", "everyone"]
MadeTier = Literal["ask", "free"]
Field = Literal["persona", "model", "effort"]
Language = Literal["python", "sh"]

HOST = "host"
PER_AGENT = 3
"""Proposals one agent may have waiting at once."""
TOTAL = 12
"""Proposals that may wait at once, from all agents together."""
KEEP_DECIDED = 200
SCRIPT_MAX = 20_000
DESCRIPTION_MAX = 200
REASON_MAX = 1_000
SCHEMA_MAX = 4_000
PERSONA_MAX = 8_000
NOTE_MAX = 500
SUMMARY_CLIP = 300
"""A persona's before and after are cut to this in a listing."""
NAME_PATTERN = re.compile(r"[a-z][a-z0-9_]{2,39}")
TOOL_PREFIX = "made_"
NOT_NAMES = frozenset({"scratch"})
"""Names a made tool cannot take: its folder would collide with the runs' scratch folder."""
LANGUAGES: tuple[Language, ...] = ("python", "sh")
WHO: tuple[Who, ...] = ("author", "everyone")
TIERS: tuple[MadeTier, ...] = ("ask", "free")


class ProposalError(ValueError):
    """A proposal or a decision that cannot be made; the message is a plain line for people
    (or for the model that proposed)."""


class NotFound(LookupError):
    """No such proposal or made tool."""


@dataclass(frozen=True, slots=True)
class Context:
    """Who is proposing or calling, and where: built by the composition root per job (a
    resident) or once for the host (no job, no room, no folders)."""

    agent: str
    agent_name: str
    job: str = ""
    room: str | None = None
    folders: tuple[tuple[str, Path], ...] = ()
    """The room's usable folders as (short name, absolute path), in the room's order."""


@dataclass(frozen=True, slots=True)
class Reach:
    """What a made tool may touch beyond its scratch folder, as the owner approved it."""

    folders: tuple[tuple[str, str], ...] = ()
    network: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"folders": [{"name": n, "path": p} for n, p in self.folders], "network": self.network}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Reach:
        folders = tuple((str(f["name"]), str(f["path"])) for f in data.get("folders", []))
        return cls(folders, bool(data.get("network", False)))


@dataclass(slots=True)
class ToolPart:
    name: str
    description: str
    input_schema: dict[str, Any]
    language: Language
    script: str
    sha256: str
    reach: Reach
    version: int
    replaces: int | None = None

    @property
    def tool_name(self) -> str:
        return TOOL_PREFIX + self.name

    def to_dict(self, *, script: bool = True) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": self.name,
            "tool_name": self.tool_name,
            "description": self.description,
            "input_schema": self.input_schema,
            "language": self.language,
            "sha256": self.sha256,
            "reach": self.reach.to_dict(),
            "version": self.version,
            "replaces": self.replaces,
        }
        if script:
            out["script"] = self.script
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolPart:
        language = data["language"]
        if language not in LANGUAGES:
            raise ValueError(f"unknown language {language!r}")
        replaces = data.get("replaces")
        return cls(
            name=str(data["name"]),
            description=str(data["description"]),
            input_schema=dict(data["input_schema"]),
            language=cast(Language, language),
            script=str(data["script"]),
            sha256=str(data["sha256"]),
            reach=Reach.from_dict(data["reach"]),
            version=int(data["version"]),
            replaces=None if replaces is None else int(replaces),
        )


@dataclass(slots=True)
class ChangePart:
    agent: str
    agent_name: str
    field: Field
    before: str
    after: str

    def to_dict(self, *, clip: int | None = None) -> dict[str, Any]:
        before, after = self.before, self.after
        if clip is not None:
            before, after = before[:clip], after[:clip]
        return {
            "agent": self.agent,
            "agent_name": self.agent_name,
            "field": self.field,
            "before": before,
            "after": after,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChangePart:
        name = data["field"]
        if name not in ("persona", "model", "effort"):
            raise ValueError(f"unknown field {name!r}")
        return cls(str(data["agent"]), str(data["agent_name"]), name, str(data["before"]), str(data["after"]))


@dataclass(frozen=True, slots=True)
class Decision:
    """How the owner approved a tool: who may use it, and whether each run asks."""

    who: Who
    tier: MadeTier

    def to_dict(self) -> dict[str, str]:
        return {"who": self.who, "tier": self.tier}


@dataclass(slots=True)
class Proposal:
    id: str
    kind: Kind
    status: Status
    agent: str
    agent_name: str
    job: str
    room: str | None
    title: str
    reason: str
    created_at: float
    decided_at: float | None = None
    note: str = ""
    tool: ToolPart | None = None
    change: ChangePart | None = None
    decision: Decision | None = None
    restored_at: float | None = None

    @property
    def waiting(self) -> bool:
        return self.status == "waiting"

    def detail(self) -> dict[str, Any]:
        """Everything, the script and the whole persona included."""
        return self._shape(script=True, clip=None)

    def summary(self) -> dict[str, Any]:
        """For a listing: no script, a persona's before and after cut short."""
        out = self._shape(script=False, clip=SUMMARY_CLIP)
        change = self.change
        out["clipped"] = change is not None and max(len(change.before), len(change.after)) > SUMMARY_CLIP
        return out

    def _shape(self, *, script: bool, clip: int | None) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "agent": self.agent,
            "agent_name": self.agent_name,
            "job": self.job,
            "room": self.room,
            "title": self.title,
            "reason": self.reason,
            "created_at": self.created_at,
            "decided_at": self.decided_at,
            "note": self.note,
            "tool": None if self.tool is None else self.tool.to_dict(script=script),
            "change": None if self.change is None else self.change.to_dict(clip=clip),
            "decision": None if self.decision is None else self.decision.to_dict(),
            "restored_at": self.restored_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Proposal:
        kind, status = data["kind"], data["status"]
        if kind not in ("tool", "change") or status not in ("waiting", "approved", "declined"):
            raise ValueError("unknown kind or status")
        decision = data.get("decision")
        if decision is not None and (decision["who"] not in WHO or decision["tier"] not in TIERS):
            raise ValueError("unknown decision")
        tool, change = data.get("tool"), data.get("change")
        return cls(
            id=str(data["id"]),
            kind=kind,
            status=status,
            agent=str(data["agent"]),
            agent_name=str(data["agent_name"]),
            job=str(data.get("job") or ""),
            room=data.get("room"),
            title=str(data["title"]),
            reason=str(data["reason"]),
            created_at=float(data["created_at"]),
            decided_at=_float(data.get("decided_at")),
            note=str(data.get("note") or ""),
            tool=None if tool is None else ToolPart.from_dict(tool),
            change=None if change is None else ChangePart.from_dict(change),
            decision=None if decision is None else Decision(decision["who"], decision["tier"]),
            restored_at=_float(data.get("restored_at")),
        )


def _float(value: Any) -> float | None:
    return None if value is None else float(value)
