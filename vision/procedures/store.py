"""The procedures on disk: one Markdown file each, an agent's own or shared.

    house/agents/<agent>/procedures/<name>.md   an agent's own
    house/procedures/<name>.md                  shared: every agent sees them

A file reads like this, and a person may edit it by hand:

    # Release the shop app

    When to use: Before tagging a release of the shop project.
    Author: maker
    Changed: 2026-11-13 10:22
    Opened: 3

    ## Steps

    1. Run the tests ...

Reading is tolerant, because people edit these files: a missing line takes a
default (the folder's agent as author, the file's time as changed, 0 opened),
a line that does not parse is kept as text, and a file with only a heading and
text is a procedure whose steps are that text. A procedure is named by its file
name without `.md`; one written by an agent gets a slug of its title.

Blocking; callers use `asyncio.to_thread`. One lock per vault keeps the
agents' jobs and the window's routes from writing a file at the same time.
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

AGENTS_DIR = "agents"
FOLDER = "procedures"
SHARED = "shared"
"""The owner name of the shared procedures in routes and events."""
HOST = "host"
"""The host may change every shared procedure, like its author."""

NAME_MAX = 80
WHEN_MAX = 300
STEPS_MAX = 6000
SLUG_MAX = 48
OWN_MAX = 40
SHARED_MAX = 60
TIME_FORMAT = "%Y-%m-%d %H:%M"

_AGENT = re.compile(r"[a-z0-9-]+")
_META = re.compile(r"^\s*(when to use|author|changed|opened)\s*:\s*(.*?)\s*$", re.IGNORECASE)
_STEPS = re.compile(r"^##\s+steps\s*$", re.IGNORECASE)

Changed = Callable[[str, str, str], None]
"""Called after every change with (owner, name, "saved" | "removed"); owner is an agent id or `shared`."""

type Found = list["Procedure"]
"""Procedures in a list; named because `Procedures.list` hides the builtin in the class's signatures."""

_locks: dict[Path, threading.RLock] = {}
_locks_guard = threading.Lock()


class ProcedureError(ValueError):
    """The procedures cannot do what was asked; the message is for people and the model."""


class NoSuchProcedure(ProcedureError):
    pass


@dataclass(frozen=True, slots=True)
class Procedure:
    name: str
    """The file name without `.md`: how routes and tools name it."""
    title: str
    when: str
    author: str
    shared: bool
    changed_at: float
    opened: int
    steps: str

    def summary(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "when": self.when,
            "author": self.author,
            "shared": self.shared,
            "changed_at": self.changed_at,
            "opened": self.opened,
            "chars": len(self.steps),
        }

    def as_dict(self) -> dict[str, Any]:
        return {**self.summary(), "steps": self.steps}


@dataclass(frozen=True, slots=True)
class Saved:
    """What an agent's save did, so its tool can tell the model."""

    procedure: Procedure
    replaced: bool
    """An earlier version was there."""
    moved: bool
    """The agent's own copy became the shared one."""
    shadows: bool
    """It is the agent's own and a shared one of the same name exists, which the agent no longer sees."""


def slugify(name: str) -> str:
    """Lowercase, runs of anything but `a-z0-9` as one `-`, at most 48 characters."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:SLUG_MAX].strip("-")


def check_agent(agent: str) -> str:
    if not _AGENT.fullmatch(agent):
        raise ValueError(f"not an agent id: {agent!r}")
    return agent


class Procedures:
    def __init__(self, vault_root: Path, changed: Changed | None = None, *, now: Callable[[], float] = time.time) -> None:
        self._root = vault_root
        self._changed = changed
        self._now = now
        with _locks_guard:
            self._lock = _locks.setdefault(vault_root.resolve(), threading.RLock())

    def folder(self, owner: str) -> Path:
        """Where `owner`'s procedures are: an agent id, or `shared`."""
        if owner == SHARED:
            return self._root / FOLDER
        return self._root / AGENTS_DIR / check_agent(owner) / FOLDER

    # ------------------------------------------------------------ the agent's side

    def list(self, agent: str) -> list[Procedure]:
        """The agent's own, then the shared ones its own do not shadow, each by title."""
        own, shared = self._visible(agent)
        return [*_by_title(own), *_by_title(shared)]

    def read(self, agent: str, name: str) -> Procedure:
        """One procedure the agent sees, by name or title said loosely, counting it as opened."""
        with self._lock:
            found = self._resolve(agent, name)
            opened = replace(found, opened=found.opened + 1)
            self._write(self._owner_of(agent, found), opened)
        return opened

    def save(self, agent: str, name: str, when: str, steps: str, shared: bool = False) -> Saved:
        """Create or replace one of the agent's own, or with `shared` a shared one (moving its own copy)."""
        check_agent(agent)
        title, when, steps = _title(name), _when(when), _steps(steps)
        slug = _slug_of(title)
        with self._lock:
            own = self._load_in(agent, slug)
            common = self._load_in(SHARED, slug)
            if shared:
                if common is not None and not _may_change(agent, common):
                    raise ProcedureError(_not_yours(common))
                if common is None:
                    self._room(SHARED, f"There are already {SHARED_MAX} shared procedures, the most kept. "
                               "Improve or remove one before sharing another.")
                earlier = common or own
                saved = Procedure(
                    name=common.name if common else slug,
                    title=title,
                    when=when,
                    author=common.author if common else agent,
                    shared=True,
                    changed_at=self._stamp(),
                    opened=earlier.opened if earlier else 0,
                    steps=steps,
                )
                self._write(SHARED, saved)
                if own is not None:
                    self._path(agent, own.name).unlink(missing_ok=True)
                result = Saved(saved, replaced=earlier is not None, moved=own is not None, shadows=False)
            else:
                if own is None:
                    self._room(agent, f"You already have {OWN_MAX} procedures, the most one agent keeps. "
                               "Improve one you have, or remove one you no longer need.")
                saved = Procedure(
                    name=own.name if own else slug,
                    title=title,
                    when=when,
                    author=agent,
                    shared=False,
                    changed_at=self._stamp(),
                    opened=own.opened if own else 0,
                    steps=steps,
                )
                self._write(agent, saved)
                result = Saved(saved, replaced=own is not None, moved=False, shadows=common is not None)
        if result.moved:
            self._tell(agent, saved.name, "removed")
        self._tell(SHARED if shared else agent, saved.name, "saved")
        return result

    def remove(self, agent: str, name: str) -> Procedure:
        """Remove one the agent sees: its own, or a shared one it wrote (any, for the host)."""
        with self._lock:
            found = self._resolve(agent, name)
            if found.shared and not _may_change(agent, found):
                raise ProcedureError(_not_yours(found))
            owner = self._owner_of(agent, found)
            self._path(owner, found.name).unlink(missing_ok=True)
        self._tell(owner, found.name, "removed")
        return found

    def listing(self, agent: str, room_chars: int, names: Mapping[str, str] | None = None) -> str:
        """Lines for the agent's prompt, newest changed first, within `room_chars`; "" when there are none."""
        own, shared = self._visible(agent)
        every = sorted([*own, *shared], key=lambda p: (-p.changed_at, p.name))
        lines = [_line(p, agent, names or {}) for p in every]
        kept: list[str] = []
        used = 0
        for line in lines:
            if used + len(line) + 1 > room_chars:
                break
            kept.append(line)
            used += len(line) + 1
        while len(kept) < len(lines):
            more = f"({len(lines) - len(kept)} more; list_procedures shows them all)"
            if used + len(more) <= room_chars or not kept:
                kept.append(more)
                break
            used -= len(kept.pop()) + 1
        return "\n".join(kept)

    # ------------------------------------------------------------ the owner's side

    def everything(self, agent_ids: Iterable[str]) -> tuple[dict[str, Found], Found]:
        """Each listed agent's own procedures, and the shared ones, each by title."""
        own = {a: _by_title(self._all(a)) for a in agent_ids if _AGENT.fullmatch(a) and a != SHARED}
        return own, _by_title(self._all(SHARED))

    def get(self, owner: str, name: str) -> Procedure:
        """One procedure by its exact name; reading it here does not count as opened."""
        found = self._load_exact(owner, name)
        if found is None:
            raise NoSuchProcedure(f"There is no procedure {name!r} for {owner}.")
        return found

    def edit(
        self, owner: str, name: str, *, title: str | None = None, when: str | None = None, steps: str | None = None
    ) -> Procedure:
        """The owner's change by hand: any procedure, any part; its name and author stay."""
        if title is None and when is None and steps is None:
            raise ProcedureError("Give a new title, when to use it, or new steps.")
        with self._lock:
            found = self.get(owner, name)
            edited = replace(
                found,
                title=found.title if title is None else _title(title),
                when=found.when if when is None else _when(when),
                steps=found.steps if steps is None else _steps(steps),
                changed_at=self._stamp(),
            )
            self._write(owner, edited)
        self._tell(owner, edited.name, "saved")
        return edited

    def delete(self, owner: str, name: str) -> Procedure:
        with self._lock:
            found = self.get(owner, name)
            self._path(owner, found.name).unlink(missing_ok=True)
        self._tell(owner, found.name, "removed")
        return found

    # ------------------------------------------------------------ files

    def _visible(self, agent: str) -> tuple[Found, Found]:
        """The agent's own, and the shared ones whose name none of its own takes."""
        own = self._all(check_agent(agent))
        taken = {slugify(p.name) for p in own}
        return own, [p for p in self._all(SHARED) if slugify(p.name) not in taken]

    def _resolve(self, agent: str, name: str) -> Procedure:
        wanted = " ".join(str(name).split())
        if not wanted:
            raise NoSuchProcedure("Say which procedure, by its name or title.")
        own, shared = self._visible(agent)
        every = [*own, *shared]
        slug = slugify(wanted)
        for test in (
            lambda p: bool(slug) and slugify(p.name) == slug,
            lambda p: p.title.casefold() == wanted.casefold(),
        ):
            for p in every:
                if test(p):
                    return p
        known = ", ".join(p.name for p in every[:20]) or "none yet"
        raise NoSuchProcedure(f"There is no procedure called {wanted!r}. Yours and the shared ones: {known}.")

    def _owner_of(self, agent: str, found: Procedure) -> str:
        return SHARED if found.shared else agent

    def _all(self, owner: str) -> Found:
        folder = self.folder(owner)
        if not folder.is_dir():
            return []
        found = (self._parse(owner, path) for path in sorted(folder.glob("*.md")) if not path.name.startswith("."))
        return [p for p in found if p is not None]

    def _load_in(self, owner: str, slug: str) -> Procedure | None:
        """The procedure whose name slugs to `slug`, so a hand-named file is replaced, not doubled."""
        return next((p for p in self._all(owner) if slugify(p.name) == slug), None)

    def _load_exact(self, owner: str, name: str) -> Procedure | None:
        if owner != SHARED and not _AGENT.fullmatch(owner):
            return None
        return next((p for p in self._all(owner) if p.name == name), None)

    def _path(self, owner: str, name: str) -> Path:
        return self.folder(owner) / f"{name}.md"

    def _room(self, owner: str, refusal: str) -> None:
        if len(self._all(owner)) >= (SHARED_MAX if owner == SHARED else OWN_MAX):
            raise ProcedureError(refusal)

    def _parse(self, owner: str, path: Path) -> Procedure | None:
        try:
            text = path.read_text(encoding="utf-8")
            mtime = path.stat().st_mtime
        except (OSError, UnicodeDecodeError):
            return None
        title, meta, steps = _split(text)
        author = meta.get("author", "")
        if owner != SHARED:
            author = owner
        elif not _AGENT.fullmatch(author):
            author = HOST
        opened = meta.get("opened", "")
        return Procedure(
            name=path.stem,
            title=title or path.stem.replace("-", " "),
            when=" ".join(meta.get("when to use", "").split()),
            author=author,
            shared=owner == SHARED,
            changed_at=_parse_time(meta.get("changed", "")) or mtime,
            opened=int(opened) if opened.isdigit() else 0,
            steps=steps,
        )

    def _write(self, owner: str, procedure: Procedure) -> None:
        path = self._path(owner, procedure.name)
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_private(path, _format(procedure).encode("utf-8"))

    def _stamp(self) -> float:
        """Now, to the minute the file can say, so what is saved reads back the same."""
        return _parse_time(_time_words(self._now())) or self._now()

    def _tell(self, owner: str, name: str, change: str) -> None:
        if self._changed is not None:
            self._changed(owner, name, change)


# ------------------------------------------------------------ the rules


def _clean_line(value: object, what: str, most: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProcedureError(f"The procedure needs {what}.")
    line = " ".join(value.split())
    if len(line) > most:
        raise ProcedureError(f"{what[0].upper()}{what[1:]} must be at most {most} characters; it has {len(line)}.")
    return line


def _title(value: object) -> str:
    return _clean_line(value, "a name", NAME_MAX)


def _when(value: object) -> str:
    return _clean_line(value, "a line on when to use it", WHEN_MAX)


def _steps(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProcedureError("The procedure needs its steps.")
    text = value.replace("\r\n", "\n").strip()
    if len(text) > STEPS_MAX:
        raise ProcedureError(
            f"The steps must be at most {STEPS_MAX:,} characters; they have {len(text):,}. Keep only what someone needs to follow them."
        )
    return text


def _slug_of(title: str) -> str:
    slug = slugify(title)
    if not slug:
        raise ProcedureError("The procedure's name needs at least one letter or digit.")
    return slug


def _may_change(agent: str, shared: Procedure) -> bool:
    return agent in (shared.author, HOST)


def _not_yours(shared: Procedure) -> str:
    return (
        f"The shared procedure “{shared.title}” was written by {shared.author}; only they or the host can change "
        "or remove it. Save your own version without sharing it instead."
    )


def _line(p: Procedure, agent: str, names: Mapping[str, str]) -> str:
    whose = ""
    if p.shared:
        whose = " (shared by you)" if p.author == agent else f" (shared by {names.get(p.author, p.author)})"
    return f"- {p.title}{whose}: {p.when}" if p.when else f"- {p.title}{whose}"


def _by_title(found: list[Procedure]) -> list[Procedure]:
    return sorted(found, key=lambda p: (p.title.casefold(), p.name))


# ------------------------------------------------------------ the file format


def _split(text: str) -> tuple[str, dict[str, str], str]:
    """The heading, the known `Key: value` lines, and the steps (with any other text before them)."""
    lines = text.replace("\r\n", "\n").split("\n")
    title = ""
    start = 0
    while start < len(lines) and not lines[start].strip():
        start += 1
    if start < len(lines) and re.match(r"^#\s+\S", lines[start]):
        title = " ".join(lines[start].lstrip("#").split())
        start += 1
    rest = lines[start:]
    cut = next((i for i, line in enumerate(rest) if _STEPS.match(line.strip())), None)
    head, tail = (rest, []) if cut is None else (rest[:cut], rest[cut + 1 :])
    meta: dict[str, str] = {}
    loose: list[str] = []
    for line in head:
        found = _META.match(line)
        if found and found.group(1).lower() not in meta:
            meta[found.group(1).lower()] = found.group(2)
        else:
            loose.append(line)
    parts = ("\n".join(loose).strip(), "\n".join(tail).strip())
    return title, meta, "\n\n".join(p for p in parts if p)


def _format(p: Procedure) -> str:
    return (
        f"# {p.title}\n\n"
        f"When to use: {p.when}\n"
        f"Author: {p.author}\n"
        f"Changed: {_time_words(p.changed_at)}\n"
        f"Opened: {p.opened}\n\n"
        f"## Steps\n\n{p.steps}\n"
    )


def _time_words(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime(TIME_FORMAT)


def _parse_time(words: str) -> float | None:
    for form in (TIME_FORMAT, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(words.strip(), form).timestamp()
        except ValueError:
            continue
    return None


def _write_private(path: Path, data: bytes) -> None:
    """Write through a temporary file and a rename, readable by the owner only."""
    temp = path.with_name(f".{path.name}.tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    os.replace(temp, path)
