"""A resident's own notes: `$VISION_HOME/house/agents/<id>/notes/`.

The same Markdown as the host's notes (one file per day, each note under a
`## HH:MM:SS` heading), written and read through the vault's own code, so a
person can read and edit them the same way. Each resident sees only its own
folder: its `remember` writes there and its `recall` searches there, never
the host's notes or another resident's. The folder is small, so a search
reads the files and ranks notes by the query's words; no index is kept.
Blocking; callers use `asyncio.to_thread`.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from vision.memory.vault import Note, Vault

AGENTS_DIR = "agents"


class ResidentNotes:
    def __init__(self, vault_root: Path, agent: str) -> None:
        if not re.fullmatch(r"[a-z0-9-]+", agent):
            raise ValueError(f"not an agent id: {agent!r}")
        self._vault = Vault(vault_root / AGENTS_DIR / agent)

    @property
    def folder(self) -> Path:
        return self._vault.notes_dir

    def remember(self, text: str, now: datetime | None = None) -> None:
        if text.strip():
            self._vault.append_note(text, now or datetime.now())

    def notes(self) -> list[Note]:
        """Every note, newest first."""
        found = [n for path in self._vault.note_paths() for n in self._vault.read_notes(path)]
        return sorted(found, key=lambda n: n.ts, reverse=True)

    def recall(self, query: str, limit: int = 5) -> list[Note]:
        """Notes holding the query's words, most words first, then newest."""
        words = {w for w in re.findall(r"\w+", query.lower()) if len(w) > 1}
        if not words:
            return []
        scored = []
        for note in self.notes():
            text = note.text.lower()
            score = sum(1 for w in words if w in text)
            if score:
                scored.append((score, note.ts, note))
        scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
        return [s[2] for s in scored[:limit]]

    def recent(self, room: int) -> str:
        """The newest notes as lines, within `room` characters, for the system prompt."""
        lines: list[str] = []
        used = 0
        for note in self.notes():
            line = f"- [{datetime.fromtimestamp(note.ts):%Y-%m-%d %H:%M}] {note.text}"
            if used + len(line) + 1 > room:
                break
            lines.append(line)
            used += len(line) + 1
        return "\n".join(lines)
