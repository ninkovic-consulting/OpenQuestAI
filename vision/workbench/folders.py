"""A room's project folders, and which one a path the model gave belongs to.

Every path starts with a folder's short name (`vision.core.folders`), with
one folder as with eight: `shop-api/src/app.py`, and `.` stands for all of
them. So a path a resident wrote down keeps its meaning when the owner adds
another folder later. Each folder is its own `ProjectRoot`, so every safety
rule holds per folder: a path addressed through one folder must stay inside
that one, and a link from it into another folder of the room is refused
like any link out.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path, PurePosixPath

from vision.core.folders import folder_names
from vision.gate.tools import ToolFailure
from vision.workbench.paths import PathRefused, ProjectRoot

ALL = "."


class Folders:
    """The folders the workbench works in, in the room's order; the first is the default."""

    def __init__(self, roots: Sequence[Path]) -> None:
        if not roots:
            raise ValueError("there is no project folder to work in")
        self.names = folder_names(roots)
        self.roots = [ProjectRoot(root, name) for root, name in zip(roots, self.names, strict=True)]
        if len({root.real for root in self.roots}) < len(self.roots):
            raise ValueError("the same folder is attached twice")

    @property
    def first(self) -> ProjectRoot:
        return self.roots[0]

    def listed(self) -> str:
        return ", ".join(f"`{name}`" for name in self.names)

    def route(self, raw: object) -> tuple[ProjectRoot, str] | None:
        """The folder `raw` is in and the path inside it; None when it means all the folders."""
        rel = ProjectRoot.parse(raw if raw not in (None, "") else ALL)
        if not rel.parts:
            return None
        root = self.named(rel.parts[0])
        if root is None:
            raise PathRefused(
                f"`{rel}` does not start with one of this room's folders: {self.listed()}. Start every "
                f"path with a folder's name, for example `{self.names[0]}/README.md`; `.` lists them all."
            )
        return root, str(PurePosixPath(*rel.parts[1:])) if len(rel.parts) > 1 else ALL

    def one(self, raw: object) -> tuple[ProjectRoot, str]:
        """Like `route`, for a tool that works on one file: all the folders at once is refused."""
        found = self.route(raw)
        if found is None:
            raise PathRefused(
                f"Give a path that starts with one of this room's folders: {self.listed()}; "
                f"for example `{self.names[0]}/README.md`."
            )
        return found

    def named(self, name: object) -> ProjectRoot | None:
        """The folder with this short name (case is ignored, as the Mac's disk does)."""
        if not isinstance(name, str):
            return None
        wanted = name.casefold()
        return next((root for root, own in zip(self.roots, self.names, strict=True) if own.casefold() == wanted), None)

    def for_program(self, raw: object) -> ProjectRoot:
        """The folder a program runs in: the one named, else the first."""
        if raw is None or raw == "":
            return self.first
        root = self.named(raw)
        if root is None:
            raise ToolFailure(f"`folder` must be the name of one of this room's folders: {self.listed()}.")
        return root
