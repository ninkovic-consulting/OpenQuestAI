"""The SQLite log at `$VISION_HOME/log.db`: turns, audit, and full-text search.

One connection shared by every thread, serialised by a lock. All methods
block; callers run them with `asyncio.to_thread`. The database and its `-wal`
and `-shm` files are private to the user (mode 0600).

A turn's `images` column holds the images the owner's message carried, as JSON
(`[{"id", "width", "height"}]`); the files themselves are in
`$VISION_HOME/images/` (`vision.attachments`).
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path

from vision.core.interfaces import AuditRecord, Hit, ImageRef, TurnRecord
from vision.memory.vault import Note

_SCHEMA = """
CREATE TABLE IF NOT EXISTS turns (
    turn_id TEXT PRIMARY KEY,
    started_at REAL NOT NULL,
    ended_at REAL NOT NULL,
    source TEXT NOT NULL,
    user_text TEXT NOT NULL,
    reply TEXT NOT NULL,
    status TEXT NOT NULL,
    brain TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    error TEXT NOT NULL,
    images TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS turns_started ON turns (started_at);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    tool TEXT NOT NULL,
    args TEXT NOT NULL,
    tier TEXT NOT NULL,
    decision TEXT NOT NULL,
    result TEXT NOT NULL,
    request_id TEXT NOT NULL,
    agent TEXT NOT NULL DEFAULT '',
    job TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS note_files (
    path TEXT PRIMARY KEY,
    mtime_ns INTEGER NOT NULL,
    size INTEGER NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts USING fts5(
    turn_id UNINDEXED, user_text, reply, tokenize = 'porter unicode61'
);
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
    path UNINDEXED, ts UNINDEXED, text, tokenize = 'porter unicode61'
);
"""

_TURN_COLUMNS = (
    "turn_id, started_at, ended_at, source, user_text, reply, status, brain, model, "
    "input_tokens, output_tokens, error, images"
)
_SNIPPET_TOKENS = 32
_AUDIT_COLUMNS = "ts, tool, args, tier, decision, result, request_id, agent, job"
_ADDED_AUDIT_COLUMNS = ("agent", "job")
"""Columns added after the first release; older logs get them on open."""
_ADDED_TURN_COLUMNS = {"images": "TEXT NOT NULL DEFAULT '[]'"}


def _turn(row: tuple[object, ...]) -> TurnRecord:
    *fields, images = row
    refs = tuple(ImageRef(str(i["id"]), int(i["width"]), int(i["height"])) for i in json.loads(str(images)))
    return TurnRecord(*fields, images=refs)  # type: ignore[arg-type]


class Log:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._db: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    def open(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # SQLite gives the -wal and -shm files the database file's mode, so
        # create it private before connecting.
        os.close(os.open(self._path, os.O_RDWR | os.O_CREAT, 0o600))
        db = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=NORMAL")
        db.execute("PRAGMA busy_timeout=5000")
        db.executescript(_SCHEMA)
        have = {row[1] for row in db.execute("PRAGMA table_info(audit)")}
        for column in _ADDED_AUDIT_COLUMNS:
            if column not in have:
                db.execute(f"ALTER TABLE audit ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
        have = {row[1] for row in db.execute("PRAGMA table_info(turns)")}
        for column, kind in _ADDED_TURN_COLUMNS.items():
            if column not in have:
                db.execute(f"ALTER TABLE turns ADD COLUMN {column} {kind}")
        for suffix in ("", "-wal", "-shm"):
            path = self._path.with_name(self._path.name + suffix)
            if path.exists():
                os.chmod(path, 0o600)
        self._db = db

    def close(self) -> None:
        with self._lock:
            if self._db is not None:
                self._db.close()
                self._db = None

    def _conn(self) -> sqlite3.Connection:
        if self._db is None:
            raise RuntimeError("the log is not open; call start() first")
        return self._db

    # ------------------------------------------------------------ turns and audit

    def add_turn(self, t: TurnRecord) -> None:
        with self._lock:
            db = self._conn()
            db.execute("BEGIN")
            try:
                db.execute("DELETE FROM turns_fts WHERE turn_id = ?", (t.turn_id,))
                db.execute(
                    f"INSERT OR REPLACE INTO turns ({_TURN_COLUMNS}) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        t.turn_id, t.started_at, t.ended_at, t.source, t.user_text, t.reply,
                        t.status, t.brain, t.model, t.input_tokens, t.output_tokens, t.error,
                        json.dumps([dataclasses.asdict(i) for i in t.images]),
                    ),
                )
                db.execute(
                    "INSERT INTO turns_fts (turn_id, user_text, reply) VALUES (?,?,?)",
                    (t.turn_id, t.user_text, t.reply),
                )
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise

    def add_audit(self, a: AuditRecord) -> None:
        with self._lock:
            self._conn().execute(
                f"INSERT INTO audit ({_AUDIT_COLUMNS}) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    a.ts, a.tool, json.dumps(a.args, default=str), a.tier, a.decision,
                    a.result, a.request_id, a.agent, a.job,
                ),
            )

    def history(self, limit: int) -> list[TurnRecord]:
        if limit <= 0:
            return []
        with self._lock:
            rows = self._conn().execute(
                f"SELECT {_TURN_COLUMNS} FROM turns ORDER BY started_at DESC, rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_turn(row) for row in reversed(rows)]

    def audits(self) -> list[AuditRecord]:
        with self._lock:
            rows = self._conn().execute(
                f"SELECT {_AUDIT_COLUMNS} FROM audit ORDER BY id"
            ).fetchall()
        return [AuditRecord(r[0], r[1], json.loads(r[2]), *r[3:]) for r in rows]

    # ------------------------------------------------------------ notes index

    def sync_notes(
        self, stamps: dict[str, tuple[int, int]], read: Callable[[str], list[Note]]
    ) -> None:
        """Bring the notes index in step with the files.

        `stamps` maps each note file's relative path to its (mtime_ns, size);
        `read(path)` returns that file's notes. Files that changed are
        re-indexed, files that vanished are dropped.
        """
        with self._lock:
            db = self._conn()
            known = {
                row[0]: (row[1], row[2])
                for row in db.execute("SELECT path, mtime_ns, size FROM note_files")
            }
            stale = [p for p, stamp in stamps.items() if known.get(p) != stamp]
            gone = [p for p in known if p not in stamps]
            if not stale and not gone:
                return
            db.execute("BEGIN")
            try:
                for path in gone:
                    self._drop_note_file(db, path)
                for path in stale:
                    self._drop_note_file(db, path)
                    db.executemany(
                        "INSERT INTO notes_fts (path, ts, text) VALUES (?,?,?)",
                        [(n.path, n.ts, n.text) for n in read(path)],
                    )
                    mtime, size = stamps[path]
                    db.execute(
                        "INSERT INTO note_files (path, mtime_ns, size) VALUES (?,?,?)",
                        (path, mtime, size),
                    )
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise

    @staticmethod
    def _drop_note_file(db: sqlite3.Connection, path: str) -> None:
        db.execute("DELETE FROM notes_fts WHERE path = ?", (path,))
        db.execute("DELETE FROM note_files WHERE path = ?", (path,))

    # ------------------------------------------------------------ search

    def search(self, query: str, limit: int) -> list[Hit]:
        terms = re.findall(r"\w+", query)[:16]
        if not terms or limit <= 0:
            return []
        match = " OR ".join(f'"{t}"' for t in terms)
        with self._lock:
            db = self._conn()
            notes = db.execute(
                f"SELECT path, ts, snippet(notes_fts, 2, '', '', '...', {_SNIPPET_TOKENS}), "
                "-bm25(notes_fts) FROM notes_fts WHERE notes_fts MATCH ? "
                "ORDER BY bm25(notes_fts) LIMIT ?",
                (match, limit),
            ).fetchall()
            turns = db.execute(
                f"SELECT f.turn_id, t.started_at, "
                f"snippet(turns_fts, -1, '', '', '...', {_SNIPPET_TOKENS}), -bm25(turns_fts) "
                "FROM turns_fts f JOIN turns t ON t.turn_id = f.turn_id "
                "WHERE turns_fts MATCH ? ORDER BY bm25(turns_fts) LIMIT ?",
                (match, limit),
            ).fetchall()
        hits = [Hit("note", r[2], r[0], float(r[1]), r[3]) for r in notes]
        hits += [Hit("turn", r[2], r[0], r[1], r[3]) for r in turns]
        hits.sort(key=lambda h: (h.score, h.ts), reverse=True)
        return hits[:limit]
