"""The memory core: the owner's profile, the persona, the library, then the newest notes.

The profile comes first and is never cut: it is short (its parts have length
limits), it is what every reply depends on, and the local model's shorter
core keeps the start. The persona follows whole. The library takes at most
`LIBRARY_SHARE` of the room left after those two (short documents whole,
the rest listed, `vision.memory.shared`), and the newest notes fill the rest.
"""

from __future__ import annotations

from datetime import datetime

from vision.memory import profile
from vision.memory.documents import INDEX, Library
from vision.memory.shared import library_text
from vision.memory.vault import FileStamp, Vault

LIBRARY_SHARE = 0.5
"""Most of the room left after the profile and the persona that the library may take."""


class CoreBuilder:
    """Builds the core text and caches it until a source file changes."""

    def __init__(self, vault: Vault, budget_chars: int) -> None:
        self._vault = vault
        self._library = Library(vault.root)
        self._budget = budget_chars
        self._signature: tuple[FileStamp, ...] | None = None
        self._text = ""

    def text(self) -> str:
        v = self._vault
        persona = v.persona_path()
        paths = [
            profile.path_in(v.root),
            v.library_dir / INDEX,
            *v.library_paths(),
            *v.note_paths(),
            *([persona] if persona else []),
        ]
        signature = v.stamps(paths)
        if signature != self._signature:
            self._text = self._build()
            self._signature = signature
        return self._text

    def _build(self) -> str:
        v = self._vault
        sections = [profile.prompt_text(profile.read(v.root), may_update=True), v.read_persona()]
        remaining = self._budget - sum(len(s) + 2 for s in sections)

        library = library_text(self._library, int(max(remaining, 0) * LIBRARY_SHARE))
        if library:
            sections.append(library)
            remaining -= len(library) + 2

        room = remaining - len("# Recent notes\n\n")
        notes = _fit(_note_blocks(v, room), room)
        if notes:
            sections.append("# Recent notes\n\n" + "\n".join(notes))
        return "\n\n".join(sections)


def _fit(blocks: list[str], room: int) -> list[str]:
    """Whole blocks, in order, until the next one would not fit. Never cuts a block."""
    chosen: list[str] = []
    for block in blocks:
        cost = len(block) + 2
        if cost > room:
            break
        chosen.append(block)
        room -= cost
    return chosen


def _note_blocks(vault: Vault, room: int) -> list[str]:
    """Notes newest first, reading day files newest first and stopping once `room` is covered."""
    blocks: list[str] = []
    used = 0
    for path in reversed(vault.note_paths()):
        for n in sorted(vault.read_notes(path), key=lambda n: n.ts, reverse=True):
            block = f"- [{datetime.fromtimestamp(n.ts):%Y-%m-%d %H:%M}] {n.text}"
            blocks.append(block)
            used += len(block) + 1
        if used > room:
            break
    return blocks
