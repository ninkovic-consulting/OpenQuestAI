"""Self-changes: an agent proposing a new persona, model or thinking level for itself.

Only these three fields can be proposed, and the check is here in code, not in
a prompt: the approval rules, permissions, spending caps, keys, the phone's
approval list and the app's own code are the owner's alone, so no proposal can
name them. A resident proposes only for itself; the host for itself or a
resident.

A model or effort is applied through the same settings patch the window uses
(its validation is the "normal settings validation"); a persona is the agent's
persona file in the vault, written whole. The value before is kept with the
proposal so the owner can put it back.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Any

from vision.core import effort
from vision.proposals.model import HOST, PERSONA_MAX, Field, ProposalError

ALLOWED_FIELDS: tuple[Field, ...] = ("persona", "model", "effort")
WORDS: dict[str, str] = {"persona": "persona", "model": "model", "effort": "thinking level"}
REFUSED = (
    "Only a persona, a model or a thinking level (effort) can be proposed. The approval rules, "
    "permissions, spending caps, keys, the phone's approval list and the app's own code are the "
    "owner's alone."
)
MODEL_MAX = 100
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@-]*")


def check_field(value: Any) -> Field:
    if not isinstance(value, str) or value not in ALLOWED_FIELDS:
        raise ProposalError(REFUSED)
    return value


def check_value(name: Field, value: Any) -> str:
    """The proposed value, checked on its own (against the agent's model happens later)."""
    if not isinstance(value, str):
        raise ProposalError(f"The new {WORDS[name]} must be text.")
    if name == "persona":
        if not value.strip():
            raise ProposalError("The new persona is empty.")
        if len(value) > PERSONA_MAX:
            raise ProposalError(f"The new persona is longer than {PERSONA_MAX:,} characters.")
        return str(value)
    given = value.strip()
    if name == "effort":
        if given not in effort.LEVELS:
            raise ProposalError(f"A thinking level is one of {', '.join(effort.LEVELS)}.")
        return given
    if len(given) > MODEL_MAX or not _MODEL.fullmatch(given):
        raise ProposalError("That is not a model name.")
    return given


def settings_body(agent: str, name: Field, value: str) -> dict[str, Any]:
    """The `PATCH /api/settings` body that sets a model or effort."""
    if agent == HOST:
        return {"models": {"talk" if name == "model" else "talk_effort": value}}
    return {"agents": {agent: {name: value}}}


def persona_path(vault: Path, relative: str) -> Path:
    """The persona file, which must lie inside the vault."""
    if not relative:
        raise ProposalError("This agent has no persona file to change.")
    root = vault.resolve()
    path = (vault / relative).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ProposalError("The persona file lies outside the vault, so it cannot be changed from here.")
    return path


def read_persona(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def write_persona(path: Path, text: str) -> None:
    """Write the persona whole through a temporary file beside it, keeping the file's mode."""
    try:
        mode = path.stat().st_mode & 0o777
    except OSError:
        mode = 0o644
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise
