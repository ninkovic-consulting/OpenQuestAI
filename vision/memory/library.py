"""What the library holds, in brief, for the Library room's description (`room_details`).

One entry per document (`vision.memory.documents`), newest first: its text
file, its title, the start of its first paragraph and its size. Blocking;
callers use `asyncio.to_thread`.
"""

from __future__ import annotations

from dataclasses import dataclass

from vision.core.config import Config
from vision.memory.documents import Library


@dataclass(frozen=True, slots=True)
class LibraryEntry:
    path: str
    """Relative to the vault, e.g. `library/projects.md`."""
    title: str
    gist: str
    size: int


def library_contents(config: Config, limit: int = 20) -> list[LibraryEntry]:
    return [
        LibraryEntry(f"library/{d.name}.md", d.title, d.gist, d.bytes)
        for d in Library(config.paths.house).list()[:limit]
    ]
