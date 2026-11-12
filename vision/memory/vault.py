"""The Markdown vault under `$VISION_HOME/house/`.

    notes/     what the assistant has learned: one file per day, each note under
               a `## HH:MM:SS` heading
    library/   shared knowledge the user writes by hand
    agents/    personas (`host.md` is the default one)

All of it is plain text a person can edit or delete; readers always go back to
the files, never to a cache of their own.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import date, datetime, time
from importlib import resources
from pathlib import Path

PERSONA_FILE = Path("agents/host.md")
LIBRARY_README = "README.md"
_HEADING = re.compile(r"^## (\d{2}:\d{2}(?::\d{2})?)[ \t]*$", re.MULTILINE)

FileStamp = tuple[str, int, int]
"""A file's path relative to the vault, modification time in ns, and size."""


@dataclass(frozen=True, slots=True)
class Note:
    path: str
    """Relative to the vault, e.g. `notes/2026-11-12.md`."""
    ts: float
    text: str


def bundled_template(name: str) -> str:
    return (resources.files("vision.memory") / "templates" / name).read_text(encoding="utf-8")


class Vault:
    def __init__(self, root: Path, persona: Path | None = None) -> None:
        self.root = root
        self._persona = persona

    @property
    def notes_dir(self) -> Path:
        return self.root / "notes"

    @property
    def library_dir(self) -> Path:
        return self.root / "library"

    def ensure(self) -> None:
        """Create the folders and copy in the starter files, never overwriting."""
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        self.library_dir.mkdir(parents=True, exist_ok=True)
        for name in (f"library/{LIBRARY_README}", PERSONA_FILE.as_posix()):
            target = self.root / name
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with resources.as_file(resources.files("vision.memory") / "templates" / name) as src:
                shutil.copyfile(src, target)

    # ------------------------------------------------------------ notes

    def append_note(self, text: str, now: datetime) -> str:
        """Append a timestamped note to today's file and return its relative path."""
        path = self.notes_dir / f"{now:%Y-%m-%d}.md"
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"## {now:%H:%M:%S}\n\n{text.strip()}\n\n")
        return self.relative(path)

    def note_paths(self) -> list[Path]:
        return sorted(self.notes_dir.glob("*.md")) if self.notes_dir.is_dir() else []

    def read_notes(self, path: Path) -> list[Note]:
        """The notes in one file. Text before the first heading is one note at the day's start."""
        try:
            body = path.read_text(encoding="utf-8")
            day = _file_day(path)
        except (OSError, UnicodeDecodeError):
            return []
        rel = self.relative(path)
        parts = _HEADING.split(body)
        notes: list[Note] = []
        if parts[0].strip():
            notes.append(Note(rel, datetime.combine(day, time()).timestamp(), parts[0].strip()))
        for stamp, text in zip(parts[1::2], parts[2::2], strict=True):
            clock = time.fromisoformat(stamp)
            if text.strip():
                notes.append(
                    Note(rel, datetime.combine(day, clock).timestamp(), text.strip())
                )
        return notes

    # ------------------------------------------------------------ library and persona

    def library_paths(self) -> list[Path]:
        if not self.library_dir.is_dir():
            return []
        return sorted(p for p in self.library_dir.rglob("*.md") if p.name != LIBRARY_README)

    def persona_path(self) -> Path | None:
        """The configured persona file, else `agents/host.md`, else None (use the bundled one)."""
        for candidate in (self._persona, self.root / PERSONA_FILE):
            if candidate is not None and candidate.is_file():
                return candidate
        return None

    def read_persona(self) -> str:
        path = self.persona_path()
        if path is not None:
            try:
                return path.read_text(encoding="utf-8").strip()
            except (OSError, UnicodeDecodeError):
                pass
        return bundled_template(PERSONA_FILE.as_posix()).strip()

    # ------------------------------------------------------------ change detection

    def relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def stamp(self, path: Path) -> FileStamp | None:
        try:
            st = path.stat()
        except OSError:
            return None
        return (path.as_posix(), st.st_mtime_ns, st.st_size)

    def note_stamps(self) -> dict[str, tuple[int, int]]:
        """Each note file's relative path with its (mtime_ns, size)."""
        out: dict[str, tuple[int, int]] = {}
        for path in self.note_paths():
            stamp = self.stamp(path)
            if stamp is not None:
                out[self.relative(path)] = (stamp[1], stamp[2])
        return out

    def stamps(self, paths: list[Path]) -> tuple[FileStamp, ...]:
        found = (self.stamp(p) for p in paths)
        return tuple(s for s in found if s is not None)


def _file_day(path: Path) -> date:
    try:
        return date.fromisoformat(path.stem)
    except ValueError:
        return datetime.fromtimestamp(path.stat().st_mtime).date()
