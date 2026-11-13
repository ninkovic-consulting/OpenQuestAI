"""A room's project folders: reading them from a room's table, and the rules they follow.

A room lists `folders = ["~/Projects/shop", "~/Projects/shop-api"]`, in
order, possibly none. The rules, checked whenever the house is built: at
most `MAX_ROOM_FOLDERS`; each a full path (from `/` or `~`); none the disk,
the home folder or a folder above it; none the assistant's own data folder,
a folder inside it or one that holds it (an agent there could read the token
and the settings); no folder twice and none inside another of the same room
(all compared as real paths, links followed).

Whether a folder exists is not checked when the house is built: a folder on
a disk that is not connected leaves the house as it is, and a resident's
job names it as missing. A folder newly given through the routes must
exist (`check_new`).
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from vision.core.config import touches_data_folder
from vision.house.model import MAX_ROOM_FOLDERS, HouseError


def room_folders(table: dict[str, Any], where: str) -> tuple[str, ...]:
    """The room's folders from its table, checked."""
    folders = table.get("folders", [])
    if not isinstance(folders, list) or not all(isinstance(f, str) and f.strip() for f in folders):
        raise HouseError(f'{where}: folders must be a list of folder paths, like ["~/Projects/shop"].')
    checked = tuple(f.strip() for f in folders)
    check_rules(checked, where)
    return checked


def check_rules(folders: tuple[str, ...], where: str) -> None:
    if len(folders) > MAX_ROOM_FOLDERS:
        raise HouseError(
            f"{where} lists {len(folders)} folders; a room may have at most {MAX_ROOM_FOLDERS}."
        )
    home = Path(os.path.realpath(Path.home()))
    seen: list[tuple[Path, str]] = []
    for folder in folders:
        if not folder.startswith(("/", "~")):
            raise HouseError(f"{where}: the folder {folder} must be a full path, starting with / or ~.")
        real = real_path(folder)
        if real == Path(real.anchor) or real == home or home.is_relative_to(real):
            raise HouseError(
                f"{where}: {folder} is the disk, the home folder or a folder above it, so it cannot be "
                "a project folder. Attach the folder of one project instead."
            )
        if touches_data_folder(real):
            raise HouseError(
                f"{where}: {folder} is the assistant's own data folder, a folder inside it or one that "
                "holds it, so it cannot be a project folder: an agent working there could read the "
                "assistant's settings and keys. Attach the folder of one project instead."
            )
        for other, given in seen:
            if real == other:
                raise HouseError(f"{where}: {given} and {folder} are the same folder; list it once in folders.")
            if real.is_relative_to(other) or other.is_relative_to(real):
                inner, outer = (folder, given) if real.is_relative_to(other) else (given, folder)
                raise HouseError(
                    f"{where}: {inner} is inside {outer}. A room's folders may not hold one another; "
                    "keep the outer folder alone, or only the folders inside it."
                )
        seen.append((real, folder))


def check_new(folders: Iterable[str], before: Iterable[str], where: str) -> None:
    """Every folder not already attached must be an existing folder."""
    known = set(before)
    for folder in folders:
        if folder not in known and not real_path(folder).is_dir():
            raise HouseError(f"{where}: {folder} is not a folder on this Mac, so it cannot be added to folders.")


def real_path(folder: str) -> Path:
    return Path(os.path.realpath(Path(folder).expanduser()))
