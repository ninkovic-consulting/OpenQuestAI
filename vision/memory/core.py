"""The memory core: persona, then library, then the newest notes, within a budget."""

from __future__ import annotations

from datetime import datetime

from vision.memory.vault import FileStamp, Vault

LIBRARY_SHARE = 0.5
"""Most of the room left after the persona that the library may take."""


class CoreBuilder:
    """Builds the core text and caches it until a source file changes."""

    def __init__(self, vault: Vault, budget_chars: int) -> None:
        self._vault = vault
        self._budget = budget_chars
        self._signature: tuple[FileStamp, ...] | None = None
        self._text = ""

    def text(self) -> str:
        v = self._vault
        persona = v.persona_path()
        paths = [*v.library_paths(), *v.note_paths(), *([persona] if persona else [])]
        signature = v.stamps(paths)
        if signature != self._signature:
            self._text = self._build()
            self._signature = signature
        return self._text

    def _build(self) -> str:
        v = self._vault
        sections = [v.read_persona()]
        remaining = self._budget - len(sections[0])

        library = _fit(_library_blocks(v), int(max(remaining, 0) * LIBRARY_SHARE))
        if library:
            sections.append("# Library\n\n" + "\n\n".join(library))
            remaining -= len(sections[-1])

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


def _library_blocks(vault: Vault) -> list[str]:
    blocks = []
    for path in vault.library_paths():
        try:
            body = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            continue
        if body:
            blocks.append(f"## {path.stem}\n\n{body}")
    return blocks


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
