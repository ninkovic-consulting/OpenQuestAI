"""Who each agent is, read from its persona file in the vault (`house/agents/<id>.md`).

A persona starts with `# The <role>`, then a paragraph on what the agent
looks after, then `**How you speak.**` and `**What you do.**` paragraphs.
`Persona` keeps the role and the first sentence of each part. Files are read
again only when they change.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_SENTENCE = re.compile(r"(.+?[.!?])(\s|$)")


@dataclass(frozen=True, slots=True)
class Persona:
    role: str
    """`maker`, `steward` and so on; empty when the file names none."""
    about: str
    """What the agent looks after, in its first sentence."""
    manner: str
    """How it speaks, in a sentence."""
    work: str
    """What it does, in a sentence."""


EMPTY = Persona("", "", "", "")


def read(path: Path) -> Persona:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return EMPTY
    return parse(text)


def parse(text: str) -> Persona:
    role = ""
    paragraphs: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") and not role:
            role = re.sub(r"^the\s+", "", stripped[2:].strip(), flags=re.IGNORECASE)
            continue
        if not stripped:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        current.append(stripped)
    if current:
        paragraphs.append(" ".join(current))
    about = next((p for p in paragraphs if not p.startswith("**")), "")
    return Persona(role, _first(about), _first(_part(paragraphs, "How you speak.")), _first(_part(paragraphs, "What you do.")))


def _part(paragraphs: list[str], label: str) -> str:
    for p in paragraphs:
        if p.startswith(f"**{label}**"):
            return p.removeprefix(f"**{label}**").strip()
    return ""


def _first(paragraph: str) -> str:
    found = _SENTENCE.match(paragraph)
    return found.group(1).strip() if found else paragraph.strip()


class Personas:
    """Reads persona files from the vault, again only when one changes."""

    def __init__(self, vault: Path) -> None:
        self._vault = vault
        self._seen: dict[Path, tuple[int, Persona]] = {}

    def get(self, relative: str) -> Persona:
        path = self._vault / relative
        try:
            stamp = path.stat().st_mtime_ns
        except OSError:
            return EMPTY
        cached = self._seen.get(path)
        if cached is not None and cached[0] == stamp:
            return cached[1]
        persona = read(path)
        self._seen[path] = (stamp, persona)
        return persona
