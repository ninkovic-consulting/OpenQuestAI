"""Made tools on disk, and the checks around running one.

    $VISION_HOME/made-tools/<name>/manifest.json   who wrote it, the owner's choices, every version
    $VISION_HOME/made-tools/<name>/versions/<n>.py|.sh   the exact text the owner approved
    $VISION_HOME/made-tools/<name>/runs.json   the newest runs
    $VISION_HOME/made-tools/scratch/<run id>/   one run's own folder, removed after it

The manifest pins each version's sha256. A run reads the version file, hashes
it and runs exactly those bytes, so what runs is what the owner read; a file
changed on disk turns the tool off instead (status `changed`). Older versions
are kept so the owner can go back to one.

A tool's reach is never wider than the room it runs in: the folders it may
read are the approved ones that are also the usable folders of the job's room,
so the host (no room) gets none.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from vision.gate.tools import ToolFailure
from vision.proposals.model import (
    DESCRIPTION_MAX,
    LANGUAGES,
    NAME_PATTERN,
    NOT_NAMES,
    REASON_MAX,
    SCHEMA_MAX,
    SCRIPT_MAX,
    TIERS,
    TOOL_PREFIX,
    WHO,
    Language,
    MadeTier,
    ProposalError,
    Reach,
    Who,
)
from vision.proposals.store import write_private

FOLDER = "made-tools"
SCRATCH = "scratch"
FORMAT = 1
KEEP_RUNS = 50
INPUT_MAX = 32_000
RUN_TIMEOUT_S = 30.0
OUTPUT_LIMIT = 20_000
RUN_INPUT_CLIP = 500
RUN_OUTPUT_CLIP = 1_000
ENDINGS: dict[Language, str] = {"python": "py", "sh": "sh"}

ToolStatus = Literal["enabled", "disabled", "changed", "pending"]
STATUSES: tuple[ToolStatus, ...] = ("enabled", "disabled", "changed", "pending")

CHANGED_REASON = (
    "Its script changed on disk after you approved it, so it was turned off. Go back to an approved "
    "version to use it again."
)
PENDING_REASON = "A new version waits for your decision in Proposals."
OFF_REASON = "You turned it off."

_JSON_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "number": (int, float),
    "integer": (int,),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
}

log = logging.getLogger(__name__)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(slots=True)
class Version:
    """One approved version: the hash pinned at approval and what the owner approved with it."""

    version: int
    sha256: str
    approved_at: float
    proposal: str
    language: Language
    description: str
    input_schema: dict[str, Any]
    reach: Reach
    reason: str

    def listed(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "sha256": self.sha256,
            "approved_at": self.approved_at,
            "proposal": self.proposal,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.listed(),
            "language": self.language,
            "description": self.description,
            "input_schema": self.input_schema,
            "reach": self.reach.to_dict(),
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Version:
        if data["language"] not in LANGUAGES:
            raise ValueError("unknown language")
        return cls(
            version=int(data["version"]),
            sha256=str(data["sha256"]),
            approved_at=float(data["approved_at"]),
            proposal=str(data["proposal"]),
            language=cast(Language, data["language"]),
            description=str(data["description"]),
            input_schema=dict(data["input_schema"]),
            reach=Reach.from_dict(data["reach"]),
            reason=str(data["reason"]),
        )


@dataclass(slots=True)
class MadeTool:
    name: str
    author: str
    author_name: str
    created_at: float
    who: Who
    tier: MadeTier
    status: ToolStatus
    version: int
    """The version in use."""
    versions: list[Version]
    disabled_reason: str = ""
    runs: int = 0
    last_run: dict[str, Any] | None = None
    held: tuple[ToolStatus, str] | None = None
    """While a new version waits: the status and reason to go back to if it is declined."""

    @property
    def enabled(self) -> bool:
        return self.status == "enabled"

    @property
    def tool_name(self) -> str:
        return TOOL_PREFIX + self.name

    @property
    def current(self) -> Version:
        return next(v for v in self.versions if v.version == self.version)

    def find(self, n: int) -> Version | None:
        return next((v for v in self.versions if v.version == n), None)

    def summary(self) -> dict[str, Any]:
        now = self.current
        return {
            "name": self.name,
            "tool_name": self.tool_name,
            "description": now.description,
            "language": now.language,
            "author": self.author,
            "author_name": self.author_name,
            "reason": now.reason,
            "input_schema": now.input_schema,
            "reach": now.reach.to_dict(),
            "who": self.who,
            "tier": self.tier,
            "enabled": self.enabled,
            "status": self.status,
            "disabled_reason": self.disabled_reason,
            "version": self.version,
            "sha256": now.sha256,
            "versions": [v.listed() for v in self.versions],
            "created_at": self.created_at,
            "runs": self.runs,
            "last_run": self.last_run,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "author": self.author,
            "author_name": self.author_name,
            "created_at": self.created_at,
            "who": self.who,
            "tier": self.tier,
            "status": self.status,
            "disabled_reason": self.disabled_reason,
            "version": self.version,
            "versions": [v.to_dict() for v in self.versions],
            "runs": self.runs,
            "last_run": self.last_run,
            "held": None if self.held is None else {"status": self.held[0], "disabled_reason": self.held[1]},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MadeTool:
        who, tier, status = data["who"], data["tier"], data["status"]
        if who not in WHO or tier not in TIERS or status not in STATUSES:
            raise ValueError("unknown who, tier or status")
        held = data.get("held")
        if held is not None and held["status"] not in STATUSES:
            raise ValueError("unknown held status")
        tool = cls(
            name=str(data["name"]),
            author=str(data["author"]),
            author_name=str(data["author_name"]),
            created_at=float(data["created_at"]),
            who=who,
            tier=tier,
            status=status,
            version=int(data["version"]),
            versions=[Version.from_dict(v) for v in data["versions"]],
            disabled_reason=str(data.get("disabled_reason") or ""),
            runs=int(data.get("runs") or 0),
            last_run=data.get("last_run"),
            held=None if held is None else (held["status"], str(held["disabled_reason"])),
        )
        if tool.find(tool.version) is None:
            raise ValueError("the version in use is not among the versions")
        return tool


StatKey = tuple[int, int, int]


class Shelf:
    """The made-tools folder. Blocking; the service calls it through `asyncio.to_thread`
    except for the quick stat-and-hash check made while listing tools."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _folder(self, name: str) -> Path:
        return self.root / name

    def _manifest(self, name: str) -> Path:
        return self._folder(name) / "manifest.json"

    def version_path(self, name: str, n: int, language: Language) -> Path:
        return self._folder(name) / "versions" / f"{n}.{ENDINGS[language]}"

    def load_all(self) -> dict[str, MadeTool]:
        tools: dict[str, MadeTool] = {}
        if not self.root.is_dir():
            return tools
        for folder in sorted(self.root.iterdir()):
            if folder.name in NOT_NAMES or not folder.is_dir() or not NAME_PATTERN.fullmatch(folder.name):
                continue
            path = self._manifest(folder.name)
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                tool = MadeTool.from_dict(data["tool"])
                if tool.name != folder.name:
                    raise ValueError("the manifest names another tool")
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                broken = path.with_name(path.name + ".broken")
                log.warning("made tool manifest unreadable (%s); moved to %s", exc, broken)
                path.replace(broken)
                continue
            tools[tool.name] = tool
        return tools

    def _private(self, folder: Path) -> None:
        """Make `folder` and every folder between it and the shelf, each 0700 (`parents=True`
        would give the ones in between the default mode)."""
        for part in [*reversed(folder.relative_to(self.root).parents), folder.relative_to(self.root)]:
            (self.root / part).mkdir(parents=True, exist_ok=True, mode=0o700)

    def save(self, tool: MadeTool) -> None:
        self._private(self._folder(tool.name))
        body = json.dumps({"version": FORMAT, "tool": tool.to_dict()}, indent=1, ensure_ascii=False)
        write_private(self._manifest(tool.name), body)

    def write_version(self, name: str, n: int, language: Language, script: str) -> None:
        path = self.version_path(name, n, language)
        self._private(path.parent)
        write_private(path, script)

    def read_version(self, name: str, n: int, language: Language) -> bytes | None:
        try:
            return self.version_path(name, n, language).read_bytes()
        except OSError:
            return None

    def stat_key(self, name: str, n: int, language: Language) -> StatKey | None:
        try:
            st = self.version_path(name, n, language).stat()
        except OSError:
            return None
        return (st.st_ino, st.st_size, st.st_mtime_ns)

    def runs(self, name: str) -> list[dict[str, Any]]:
        try:
            data = json.loads((self._folder(name) / "runs.json").read_text(encoding="utf-8"))
            return [r for r in data["runs"] if isinstance(r, dict)]
        except (OSError, ValueError, KeyError, TypeError):
            return []

    def add_run(self, name: str, record: dict[str, Any]) -> None:
        """Keep the newest `KEEP_RUNS` runs, newest first."""
        rows = [record, *self.runs(name)][:KEEP_RUNS]
        body = json.dumps({"version": FORMAT, "runs": rows}, indent=1, ensure_ascii=False)
        write_private(self._folder(name) / "runs.json", body)

    def remove(self, name: str) -> None:
        shutil.rmtree(self._folder(name), ignore_errors=True)

    def new_scratch(self, run_id: str) -> Path:
        """An empty folder for one run (0700). Its parent must stay writable: the sandbox
        puts the run's two marker files beside it."""
        parent = self.root / SCRATCH
        self._private(parent)
        scratch = parent / run_id
        scratch.mkdir(mode=0o700)
        return scratch


# --- A tool proposal's fields ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class Draft:
    """A tool proposal's fields, checked."""

    name: str
    description: str
    input_schema: dict[str, Any]
    language: Language
    script: str
    reach: Reach
    reason: str


def draft(fields: Mapping[str, Any], folders: Sequence[tuple[str, Path]], reserved: Collection[str]) -> Draft:
    """Check what the model sent; a refusal is a `ProposalError` with a plain line."""
    name = fields.get("name")
    if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name) or name in NOT_NAMES:
        raise ProposalError(
            "The name must start with a lowercase letter and have 3 to 40 lowercase letters, digits "
            "or underscores, like count_lines."
        )
    if name in reserved or TOOL_PREFIX + name in reserved or name.startswith(TOOL_PREFIX):
        raise ProposalError(f"{name} is the name of a built-in tool or too close to one. Choose another name.")
    description = text(fields.get("description"), "description", DESCRIPTION_MAX)
    reason = text(fields.get("reason"), "reason", REASON_MAX)
    schema = _schema(fields.get("input_schema"))
    language = fields.get("language")
    if language not in LANGUAGES:
        raise ProposalError("The language must be python (standard library only) or sh (POSIX shell).")
    script = fields.get("script")
    if not isinstance(script, str) or not script.strip():
        raise ProposalError("The script is empty.")
    if len(script) > SCRIPT_MAX:
        raise ProposalError(f"The script is longer than {SCRIPT_MAX:,} characters.")
    if "\x00" in script:
        raise ProposalError("The script contains a NUL character.")
    network = fields.get("network", False)
    if not isinstance(network, bool):
        raise ProposalError("network must be true or false.")
    reach = Reach(_folders(fields.get("folders"), folders), network)
    return Draft(name, description, schema, cast(Language, language), script, reach, reason)


def text(value: Any, what: str, most: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProposalError(f"The {what} is empty.")
    given = value.strip()
    if len(given) > most:
        raise ProposalError(f"The {what} is longer than {most:,} characters.")
    return given


def _schema(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            value = None
    if not isinstance(value, dict) or value.get("type") != "object":
        raise ProposalError('input_schema must be a JSON schema object with "type": "object".')
    if len(json.dumps(value, ensure_ascii=False)) > SCHEMA_MAX:
        raise ProposalError(f"input_schema is longer than {SCHEMA_MAX:,} characters as JSON.")
    properties, required = value.get("properties", {}), value.get("required", [])
    if not isinstance(properties, dict) or not all(isinstance(p, dict) for p in properties.values()):
        raise ProposalError("input_schema's properties must be an object of property schemas.")
    if not isinstance(required, list) or not all(isinstance(r, str) for r in required):
        raise ProposalError("input_schema's required must be a list of property names.")
    return value


def _folders(value: Any, usable: Sequence[tuple[str, Path]]) -> tuple[tuple[str, str], ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ProposalError("folders must be a list of the room's folder names.")
    paths = dict(usable)
    unknown = [v for v in value if v not in paths]
    if unknown:
        if not paths:
            raise ProposalError(
                "There are no project folders here, so the tool cannot declare any. Leave folders out."
            )
        raise ProposalError(
            f"{', '.join(unknown)} is not a folder of this room. Its folders are: {', '.join(paths)}."
        )
    return tuple((name, str(paths[name])) for name in dict.fromkeys(value))


# --- Running -----------------------------------------------------------------------


def reach_for(approved: Reach, folders: Sequence[tuple[str, Path]]) -> list[tuple[str, Path]]:
    """The approved folders that lie within the job's usable folders (by real path), so a run
    never reaches further than the room it runs in. The host passes no folders and gets none."""
    usable = [os.path.realpath(path) for _, path in folders]
    out: list[tuple[str, Path]] = []
    for name, path in approved.folders:
        real = os.path.realpath(path)
        if any(real == u or real.startswith(u.rstrip("/") + "/") for u in usable):
            out.append((name, Path(path)))
    return out


def checked_input(schema: dict[str, Any], args: Any) -> bytes:
    """The input as JSON bytes after a light check against the approved schema."""
    if not isinstance(args, dict):
        raise ToolFailure("The input must be a JSON object.")
    missing = [key for key in schema.get("required", []) if key not in args]
    if missing:
        raise ToolFailure(f"The input lacks {', '.join(missing)}.")
    for key, prop in (schema.get("properties") or {}).items():
        wanted = prop.get("type") if isinstance(prop, dict) else None
        if key not in args or not isinstance(wanted, str) or wanted not in _JSON_TYPES:
            continue
        value = args[key]
        if not isinstance(value, _JSON_TYPES[wanted]) or (wanted != "boolean" and isinstance(value, bool)):
            raise ToolFailure(f"{key} must be of type {wanted}.")
    body = json.dumps(args, ensure_ascii=False)
    if len(body) > INPUT_MAX:
        raise ToolFailure(f"The input is longer than {INPUT_MAX:,} characters as JSON.")
    return body.encode("utf-8")
