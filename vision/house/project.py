"""A room's project name: what the owner calls the project the room holds.

Plain text the owner gives, such as the product's name: one line of at most
`MAX_PROJECT_NAME` characters. It is optional; blank means none. It is a
name, not a place: a value that looks like a path is refused, because the
places go in `folders`.

Residents and the host find a room by it too (`rooms_named`), so two rooms
should not share one; whoever looks a room up by it is told when they do.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from typing import Any

from vision.house.model import MAX_PROJECT_NAME, HouseError


def room_project(table: dict[str, Any], where: str) -> str | None:
    """The project name from a room's table, checked; None when the room has none."""
    value = table.get("project")
    if value is None:
        return None
    if not isinstance(value, str):
        raise HouseError(f"{where}: project must be text, like project = \"Harbor Books\".")
    return check_name(value, where)


def check_name(value: str, where: str) -> str | None:
    """`value` trimmed, or None when it is blank. Raises `HouseError` with a plain reason."""
    name = value.strip()
    if not name:
        return None
    if name.startswith(("/", "~")):
        raise HouseError(
            f"{where}: the project name {name!r} looks like a folder path. "
            "A project name is a name, such as Harbor Books; put folders in folders."
        )
    if len(name) > MAX_PROJECT_NAME:
        raise HouseError(
            f"{where}: the project name is {len(name)} characters; use at most {MAX_PROJECT_NAME}."
        )
    if any(unicodedata.category(ch)[0] == "C" or unicodedata.category(ch) in ("Zl", "Zp") for ch in name):
        raise HouseError(f"{where}: the project name must be one line of plain text.")
    return name


def rooms_named(rooms: Sequence[dict[str, Any]], wanted: str) -> list[dict[str, Any]]:
    """The plan's rooms whose project name is `wanted`, ignoring case and outer spaces."""
    key = wanted.strip().casefold()
    return [r for r in rooms if key and str(r.get("project") or "").casefold() == key]
