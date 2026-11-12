"""The tool catalog, and which tools a project folder looks like it needs.

The catalog is data in `house/tools.toml`. Built-in tools are the assistant's
own and run today; project tools are stored and shown per room, and start
working when the other agents wake up in the next slice.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from fnmatch import fnmatchcase
from functools import cache
from pathlib import Path
from typing import Any

from vision.core.programs import find_program
from vision.house import store
from vision.house.model import HouseError

CATALOG_FILE = store.DEFAULT_FILE.parent / "tools.toml"
TOOL_KEYS = {"title", "description", "built_in", "program", "markers", "remote_hosts"}
URL_HOST = re.compile(r"^\s*url\s*=\s*(?:[a-z+]+://)?(?:[^@/\s]+@)?([^:/\s]+)", re.IGNORECASE)

Finder = Callable[[str], Path | None]


@dataclass(frozen=True, slots=True)
class ToolInfo:
    id: str
    title: str
    description: str
    built_in: bool
    program: str | None
    """The command the tool needs on this Mac; None for a built-in tool."""
    markers: tuple[str, ...]
    remote_hosts: tuple[str, ...]


Catalog = dict[str, ToolInfo]


@cache
def load_catalog(path: Path = CATALOG_FILE) -> Catalog:
    """The catalog, in file order. Raises `HouseError` when the file breaks a rule."""
    doc = store.read_toml(path)
    tools = doc.get("tools")
    if set(doc) != {"tools"} or not isinstance(tools, dict):
        raise HouseError(f"{path.name} must hold only [tools.<id>] tables.")
    return {tool_id: _tool(tool_id, table) for tool_id, table in tools.items()}


def _tool(tool_id: str, table: Any) -> ToolInfo:
    where = f"Tool {tool_id!r}"
    if not isinstance(table, dict):
        raise HouseError(f"{where} must be a table.")
    unknown = sorted(set(table) - TOOL_KEYS)
    if unknown:
        raise HouseError(f"{where}: unknown setting {unknown[0]!r}.")
    built_in = table.get("built_in", False) is True
    program = table.get("program")
    if built_in == isinstance(program, str):
        raise HouseError(f"{where} needs either built_in = true or a program, not both.")
    return ToolInfo(
        id=tool_id,
        title=str(table.get("title", tool_id)),
        description=str(table.get("description", "")),
        built_in=built_in,
        program=program,
        markers=tuple(table.get("markers", ())),
        remote_hosts=tuple(h.lower() for h in table.get("remote_hosts", ())),
    )


def check_tool_ids(value: Any, where: str, catalog: Catalog | None = None) -> tuple[str, ...]:
    """Validate a `tools` list from a house file or a request; duplicates are dropped."""
    catalog = load_catalog() if catalog is None else catalog
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise HouseError(f'{where}: tools must be a list of tool ids, like ["git", "npm"].')
    for tool_id in value:
        if tool_id not in catalog:
            raise HouseError(
                f"{where}: there is no tool {tool_id!r}. Known tools: {', '.join(catalog)}."
            )
    return tuple(dict.fromkeys(value))


def with_built_ins(ids: tuple[str, ...], catalog: Catalog | None = None) -> tuple[str, ...]:
    """`ids`, then every built-in tool not already among them, in catalog order.

    The assistant's own tools run whatever a house file lists, so a file written
    before a tool existed must not hide it.
    """
    catalog = load_catalog() if catalog is None else catalog
    return tuple(dict.fromkeys([*ids, *(t.id for t in catalog.values() if t.built_in)]))


def available(tool: ToolInfo, finder: Finder = find_program) -> bool:
    """Built-in tools always are; a project tool is when its program is on this Mac."""
    return tool.built_in or (tool.program is not None and finder(tool.program) is not None)


def tool_refs(
    ids: Iterable[str], catalog: Catalog | None = None, finder: Finder = find_program
) -> list[dict[str, Any]]:
    """Tools as the plan shows them on a room: id, title, available, built_in."""
    catalog = load_catalog() if catalog is None else catalog
    return [
        {"id": t.id, "title": t.title, "available": available(t, finder), "built_in": t.built_in}
        for t in (catalog[i] for i in ids)
    ]


def catalog_entries(
    catalog: Catalog | None = None, finder: Finder = find_program
) -> list[dict[str, Any]]:
    """The whole catalog for `GET /api/house/tools`."""
    catalog = load_catalog() if catalog is None else catalog
    return [
        {
            "id": t.id,
            "title": t.title,
            "description": t.description,
            "program": t.program,
            "built_in": t.built_in,
            "available": available(t, finder),
        }
        for t in catalog.values()
    ]


def propose_tools(project_path: str | Path, catalog: Catalog | None = None) -> list[str]:
    """The project tools a folder looks like it needs, as catalog ids in catalog order.

    Looks only at the names of files and folders in the top two levels and at
    the remote hosts in `.git/config`. Reads no other file and never follows a
    symlink. Raises `NotADirectoryError` when the path is not a folder.
    """
    catalog = load_catalog() if catalog is None else catalog
    root = Path(project_path).expanduser()
    if not root.is_dir():
        raise NotADirectoryError(str(root))
    names = list(_entry_paths(root))
    hosts = _remote_hosts(root)
    return [
        t.id
        for t in catalog.values()
        if not t.built_in
        and (
            any(_matches(rel, pattern) for rel in names for pattern in t.markers)
            or any(h in hosts for h in t.remote_hosts)
        )
    ]


def _entry_paths(root: Path) -> Iterator[str]:
    """Paths inside `root`, one and two levels down, without following symlinks."""
    for entry in _scan(root):
        yield entry.name
        if entry.is_dir(follow_symlinks=False):
            for child in _scan(Path(entry.path)):
                yield f"{entry.name}/{child.name}"


def _scan(folder: Path) -> list[os.DirEntry[str]]:
    try:
        with os.scandir(folder) as it:
            return [e for e in it if not e.is_symlink()]
    except OSError:
        return []


def _matches(rel: str, pattern: str) -> bool:
    """A pattern with a slash matches the path; one without matches the last name."""
    if "/" in pattern:
        return fnmatchcase(rel, pattern)
    return fnmatchcase(rel.rsplit("/", 1)[-1], pattern)


def _remote_hosts(root: Path) -> set[str]:
    """The hosts of the remote URLs in `<root>/.git/config`, lowercased."""
    git = root / ".git"
    config = git / "config"
    if git.is_symlink() or not git.is_dir() or config.is_symlink() or not config.is_file():
        return set()
    try:
        lines = config.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return set()
    return {m.group(1).lower() for line in lines if (m := URL_HOST.match(line))}
