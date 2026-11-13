"""The library: the owner's documents, under `house/library/` in the vault.

    library/<name>.md          a document's text: written by hand, saved by the
                               assistant, pasted in the window, or taken out of
                               a file when it was added
    library/originals/<name>.* the file as it was added (text, Markdown, PDF, Word)
    library/index.json         what the text files cannot say: each added
                               document's title, kind, original and when it came
    library/.search.db         the full-text index (SQLite FTS5), rebuilt from
                               the text files whenever they change

A Markdown file dropped into the folder by hand is a document too (kind
`note`), titled by its first heading. Everything but the index is plain text a
person can read and edit; the index of words is a cache kept beside the files
so backups, resets and restores carry it with them, and is rebuilt from the
files whenever they differ.

Documents are not loaded whole into every conversation: the memory core lists
them (`vision.memory.shared`), and their text is read in parts on demand.
Blocking; callers use `asyncio.to_thread`. One lock per library folder keeps
the host's tools, the residents' and the routes from writing at once.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from vision.memory.extract import MAX_TEXT_CHARS, Unreadable, check_size, extract, kind_of, tidy
from vision.memory.vault import LIBRARY_ORIGINALS as ORIGINALS
from vision.memory.vault import Vault

DocKind = Literal["note", "markdown", "text", "pdf", "docx"]
KIND_WORDS: dict[str, str] = {
    "note": "note",
    "markdown": "Markdown",
    "text": "text",
    "pdf": "PDF",
    "docx": "Word",
}
INDEX = "index.json"
SEARCH_DB = ".search.db"
TITLE_MAX = 120
MAX_DOCUMENTS = 500
PART_CHARS = 8000
"""About two thousand tokens: a part is read in one tool call without crowding the conversation."""
GIST_CHARS = 140
NAME_MAX = 60
SEARCH_LIMIT = 8

_locks: dict[Path, threading.RLock] = {}
_locks_guard = threading.Lock()
_seen: dict[str, tuple[int, int, tuple[str, str, int, int]]] = {}
"""Each text file's (mtime_ns, size) with its (heading, gist, characters, parts), so listing a
large library does not read and split every text each time."""


class LibraryError(ValueError):
    """The library cannot do what was asked; the message is for people (and the model)."""


class NoSuchDocument(LibraryError):
    pass


@dataclass(frozen=True, slots=True)
class Document:
    name: str
    """How tools and routes name it: the text file's path in the library, without `.md`."""
    title: str
    kind: DocKind
    chars: int
    """Characters of text."""
    bytes: int
    """The original file's size, or the text's when there is none."""
    added_at: float
    gist: str
    original: str | None
    """The original file, relative to the library folder, when one was kept."""
    parts: int
    """How many parts `read_document` gives it in."""

    @property
    def editable(self) -> bool:
        """Its text may be changed: it was written, not taken from a file."""
        return self.kind == "note"

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "kind": self.kind,
            "chars": self.chars,
            "bytes": self.bytes,
            "parts": self.parts,
            "added_at": self.added_at,
            "gist": self.gist,
            "original": self.original,
            "editable": self.editable,
        }


@dataclass(frozen=True, slots=True)
class Part:
    document: Document
    number: int
    count: int
    text: str


@dataclass(frozen=True, slots=True)
class DocHit:
    document: Document
    part: int
    snippet: str


class Library:
    def __init__(self, vault_root: Path) -> None:
        self.folder = vault_root / "library"
        key = self.folder.resolve()
        with _locks_guard:
            self._lock = _locks.setdefault(key, threading.RLock())

    # ------------------------------------------------------------ reading

    def list(self) -> list[Document]:
        """Every document, newest first."""
        with self._lock:
            index = self._index()
            docs = [self._document(path, index) for path in self._text_files()]
        found = [d for d in docs if d is not None]
        return sorted(found, key=lambda d: (-d.added_at, d.name))

    def find(self, ref: str) -> Document:
        """A document by its name, or its title said loosely. Raises `NoSuchDocument`."""
        wanted = " ".join(str(ref).split()).casefold().removesuffix(".md")
        docs = self.list()
        if not wanted:
            raise NoSuchDocument("Say which document, by its name or title.")
        for test in (
            lambda d: d.name.casefold() == wanted,
            lambda d: d.title.casefold() == wanted,
            lambda d: wanted in d.name.casefold() or wanted in d.title.casefold(),
        ):
            hits = [d for d in docs if test(d)]
            if len(hits) == 1:
                return hits[0]
            if len(hits) > 1:
                names = ", ".join(f"{d.name} ({d.title})" for d in hits[:8])
                raise NoSuchDocument(f"Several documents match {ref!r}: {names}. Say which, by name.")
        known = ", ".join(d.name for d in docs[:12]) or "none yet"
        raise NoSuchDocument(f"There is no document called {ref!r}. The library has: {known}.")

    def text(self, ref: str) -> tuple[Document, str]:
        doc = self.find(ref)
        return doc, self._read_text(doc.name)

    def read(self, ref: str, part: int = 1) -> Part:
        """One part of a document's text. Raises `LibraryError` for a part it does not have."""
        doc, text = self.text(ref)
        parts = split_parts(text)
        if not 1 <= part <= len(parts):
            raise LibraryError(f"{doc.title!r} has {len(parts)} {_plural(len(parts), 'part')}; ask for 1 to {len(parts)}.")
        return Part(doc, part, len(parts), parts[part - 1])

    def search(self, query: str, limit: int = SEARCH_LIMIT) -> list[DocHit]:
        """Parts whose words match the query, best first, with a snippet each."""
        terms = re.findall(r"\w+", query)[:16]
        if not terms:
            return []
        match = " OR ".join(f'"{t}"' for t in terms)
        docs = {d.name: d for d in self.list()}
        with self._lock, self._search_db() as db:
            self._sync(db, docs)
            rows = db.execute(
                "SELECT name, part, snippet(parts, 3, '«', '»', '…', 24) FROM parts "
                "WHERE parts MATCH ? ORDER BY bm25(parts, 0, 0, 4.0, 1.0) LIMIT ?",
                (match, limit),
            ).fetchall()
        return [DocHit(docs[name], int(part), " ".join(str(snip).split())) for name, part, snip in rows if name in docs]

    # ------------------------------------------------------------ changing

    def add_text(self, title: str, text: str) -> Document:
        """Save a written document (kind `note`). Raises `LibraryError`."""
        title = clean_title(title)
        body = _clean_text(text)
        with self._lock:
            self._room_for_one()
            name = self._new_name(title)
            self._write_text(name, body)
            self._set_entry(name, {"title": title, "kind": "note", "added_at": time.time()})
            return self.find_exact(name)

    def add_file(self, filename: str, data: bytes, title: str | None = None) -> Document:
        """Add a file: its text is taken now, and the file is kept as the original. Raises `LibraryError`."""
        base = Path(filename).name
        try:
            kind_of(base)
            got = extract(base, data)
        except Unreadable as exc:
            raise LibraryError(str(exc)) from None
        title = clean_title(title or Path(base).stem.replace("_", " "))
        with self._lock:
            self._room_for_one()
            name = self._new_name(title)
            original = f"{ORIGINALS}/{name}{Path(base).suffix.casefold()}"
            (self.folder / ORIGINALS).mkdir(parents=True, exist_ok=True)
            _write_private(self.folder / original, data)
            self._write_text(name, got.text)
            self._set_entry(
                name,
                {"title": title, "kind": got.kind, "added_at": time.time(), "original": original, "file_name": base},
            )
            return self.find_exact(name)

    def update(self, ref: str, *, title: str | None = None, text: str | None = None, append: bool = False) -> Document:
        """Rename a document, or change a written one's text (replace, or add to its end)."""
        with self._lock:
            doc = self.find(ref)
            if text is not None:
                if not doc.editable:
                    raise LibraryError(
                        f"{doc.title!r} was added from a {KIND_WORDS[doc.kind]} file, and its text stays as "
                        "the file has it. Save the new text as a document of its own instead."
                    )
                new = _clean_text(text)
                if append:
                    new = f"{self._read_text(doc.name).rstrip()}\n\n{new}"
                    check_or_refuse(new)
                self._write_text(doc.name, new)
            if title is not None:
                self._set_entry(doc.name, {"title": clean_title(title)})
            return self.find_exact(doc.name)

    def remove(self, ref: str) -> Document:
        """Delete a document's text, its original and its entry."""
        with self._lock:
            doc = self.find(ref)
            for rel in (f"{doc.name}.md", doc.original):
                if rel:
                    (self.folder / rel).unlink(missing_ok=True)
            index = self._index()
            if index.pop(doc.name, None) is not None:
                self._write_index(index)
            return doc

    def find_exact(self, name: str) -> Document:
        doc = self._document(self.folder / f"{name}.md", self._index())
        if doc is None:
            raise NoSuchDocument(f"There is no document called {name!r}.")
        return doc

    # ------------------------------------------------------------ files

    def _text_files(self) -> list[Path]:
        return Vault(self.folder.parent).library_paths()

    def _document(self, path: Path, index: dict[str, dict[str, Any]]) -> Document | None:
        name = path.relative_to(self.folder).with_suffix("").as_posix()
        try:
            stat = path.stat()
            seen = _seen.get(path.as_posix())
            if seen is None or seen[:2] != (stat.st_mtime_ns, stat.st_size):
                text = path.read_text(encoding="utf-8").strip()
                heading, gist = title_and_gist(text)
                seen = (stat.st_mtime_ns, stat.st_size, (heading, gist, len(text), len(split_parts(text))))
                _seen[path.as_posix()] = seen
        except (OSError, UnicodeDecodeError):
            return None
        heading, gist, chars, parts = seen[2]
        entry = index.get(name, {})
        original = entry.get("original")
        size = stat.st_size
        if isinstance(original, str):
            try:
                size = (self.folder / original).stat().st_size
            except OSError:
                original = None
        kind = entry.get("kind")
        return Document(
            name=name,
            title=str(entry.get("title") or heading or path.stem.replace("-", " ")),
            kind=kind if kind in KIND_WORDS else "note",
            chars=chars,
            bytes=size,
            added_at=float(entry.get("added_at") or stat.st_mtime),
            gist=gist,
            original=original if isinstance(original, str) else None,
            parts=parts,
        )

    def _read_text(self, name: str) -> str:
        try:
            return (self.folder / f"{name}.md").read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            raise NoSuchDocument(f"The text of {name!r} cannot be read.") from None

    def _write_text(self, name: str, text: str) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        _write_private(self.folder / f"{name}.md", (text.strip() + "\n").encode("utf-8"))

    def _new_name(self, title: str) -> str:
        base = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")[:NAME_MAX].strip("-") or "document"
        taken = {d.name for d in self.list()} | set(self._index())
        name, n = base, 2
        while name in taken or (self.folder / f"{name}.md").exists():
            name, n = f"{base}-{n}", n + 1
        return name

    def _room_for_one(self) -> None:
        if len(self._text_files()) >= MAX_DOCUMENTS:
            raise LibraryError(f"The library holds {MAX_DOCUMENTS} documents, its most. Remove one first.")

    def _index(self) -> dict[str, dict[str, Any]]:
        try:
            data = json.loads((self.folder / INDEX).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        docs = data.get("documents") if isinstance(data, dict) else None
        return {k: v for k, v in docs.items() if isinstance(v, dict)} if isinstance(docs, dict) else {}

    def _set_entry(self, name: str, values: dict[str, Any]) -> None:
        index = self._index()
        index[name] = {**index.get(name, {}), **values}
        self._write_index(index)

    def _write_index(self, index: dict[str, dict[str, Any]]) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        body = json.dumps({"version": 1, "documents": index}, indent=2, ensure_ascii=False)
        _write_private(self.folder / INDEX, (body + "\n").encode("utf-8"))

    # ------------------------------------------------------------ the index of words

    @contextmanager
    def _search_db(self) -> Iterator[sqlite3.Connection]:
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / SEARCH_DB
        os.close(os.open(path, os.O_RDWR | os.O_CREAT, 0o600))
        db = sqlite3.connect(path, isolation_level=None)
        try:
            db.execute("PRAGMA busy_timeout=5000")
            db.executescript(
                "CREATE TABLE IF NOT EXISTS files (name TEXT PRIMARY KEY, stamp TEXT NOT NULL);"
                "CREATE VIRTUAL TABLE IF NOT EXISTS parts USING fts5("
                "name UNINDEXED, part UNINDEXED, title, text, tokenize = 'porter unicode61');"
            )
            yield db
        finally:
            db.close()

    def _sync(self, db: sqlite3.Connection, docs: dict[str, Document]) -> None:
        """Re-index the documents whose text or title changed; drop the ones that are gone."""
        stamps: dict[str, str] = {}
        for name, doc in docs.items():
            try:
                st = (self.folder / f"{name}.md").stat()
            except OSError:
                continue
            stamps[name] = f"{st.st_mtime_ns}:{st.st_size}:{doc.title}"
        known = dict(db.execute("SELECT name, stamp FROM files").fetchall())
        stale = [n for n, s in stamps.items() if known.get(n) != s]
        gone = [n for n in known if n not in stamps]
        if not stale and not gone:
            return
        db.execute("BEGIN")
        try:
            for name in [*gone, *stale]:
                db.execute("DELETE FROM parts WHERE name = ?", (name,))
                db.execute("DELETE FROM files WHERE name = ?", (name,))
            for name in stale:
                text = self._read_text(name)
                db.executemany(
                    "INSERT INTO parts (name, part, title, text) VALUES (?,?,?,?)",
                    [(name, i, docs[name].title, p) for i, p in enumerate(split_parts(text), 1)],
                )
                db.execute("INSERT INTO files (name, stamp) VALUES (?,?)", (name, stamps[name]))
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise


# ------------------------------------------------------------------ text helpers


def clean_title(title: object) -> str:
    text = " ".join(title.split()) if isinstance(title, str) else ""
    if not text or len(text) > TITLE_MAX or any(ord(c) < 32 or ord(c) == 127 for c in text):
        raise LibraryError(f"A document's title must be 1 to {TITLE_MAX} characters of plain text.")
    return text


def _clean_text(text: object) -> str:
    if not isinstance(text, str):
        raise LibraryError("Send the document's text as text.")
    body = tidy(text)
    if not body:
        raise LibraryError("The document has no text.")
    check_or_refuse(body)
    return body


def check_or_refuse(text: str) -> None:
    try:
        check_size(text)
    except Unreadable as exc:
        raise LibraryError(str(exc)) from None


def split_parts(text: str, size: int = PART_CHARS) -> list[str]:
    """The text in parts of at most `size` characters, cut at a paragraph, else a line, else a space."""
    text = text.strip()
    parts: list[str] = []
    while len(text) > size:
        window = text[:size]
        cut = max(window.rfind("\n\n"), 0)
        if cut < size // 2:
            cut = window.rfind("\n")
        if cut < size // 2:
            cut = window.rfind(" ")
        if cut < size // 2:
            cut = size
        parts.append(text[:cut].strip())
        text = text[cut:].strip()
    if text or not parts:
        parts.append(text)
    return parts


def title_and_gist(text: str) -> tuple[str, str]:
    """The first `#` heading, and the start of the first paragraph on one line."""
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
        if sum(len(p) for p in paragraph) > GIST_CHARS:
            break
    gist = " ".join(paragraph)
    if len(gist) > GIST_CHARS:
        gist = gist[: GIST_CHARS - 1].rstrip() + "…"
    return title, gist


def size_words(n: int) -> str:
    if n < 1024:
        return f"{n} bytes"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def _plural(n: int, word: str) -> str:
    return word if n == 1 else f"{word}s"


def _write_private(path: Path, data: bytes) -> None:
    """Write through a temporary file and a rename, readable by the owner only."""
    temp = path.with_name(f".{path.name}.tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    os.replace(temp, path)


__all__ = [
    "MAX_TEXT_CHARS",
    "DocHit",
    "Document",
    "Library",
    "LibraryError",
    "NoSuchDocument",
    "Part",
]
