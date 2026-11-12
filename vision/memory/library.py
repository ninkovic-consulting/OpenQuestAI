"""What the library holds, in brief: one entry per Markdown file under `house/library/`.

The library is what the user writes by hand for the assistant to always know
(the README that explains it is left out). Each entry is the file, its title
(its first `#` heading, else its name) and the start of its first paragraph.
Blocking; callers use `asyncio.to_thread`.
"""

from __future__ import annotations

from dataclasses import dataclass

from vision.core.config import Config
from vision.memory.vault import Vault

GIST_CHARS = 140


@dataclass(frozen=True, slots=True)
class LibraryEntry:
    path: str
    """Relative to the vault, e.g. `library/projects.md`."""
    title: str
    gist: str
    size: int


def library_contents(config: Config, limit: int = 20) -> list[LibraryEntry]:
    vault = Vault(config.paths.house)
    entries: list[LibraryEntry] = []
    for path in vault.library_paths()[:limit]:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        title, gist = _title_and_gist(text)
        entries.append(LibraryEntry(vault.relative(path), title or path.stem.replace("-", " "), gist, len(text)))
    return entries


def _title_and_gist(text: str) -> tuple[str, str]:
    title = ""
    paragraph: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            if not title and stripped.lstrip("#").strip():
                title = stripped.lstrip("#").strip()
            if paragraph:
                break
            continue
        if not stripped:
            if paragraph:
                break
            continue
        paragraph.append(stripped)
    gist = " ".join(paragraph)
    if len(gist) > GIST_CHARS:
        gist = gist[: GIST_CHARS - 1].rstrip() + "…"
    return title, gist
