"""Turning a path inside one of the room's folders into a real path inside that folder.

Every path is resolved for real (symbolic links followed, by the operating
system's rules) and then compared component by component with the real
project folder. Nothing relies on string prefixes. A refusal says why in
words the model can act on, and never names a place outside the project.
"""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from vision.gate.tools import ToolFailure
from vision.workbench.protected import HOOK_FOLDERS, is_git_internal, is_protected

MAX_PATH_CHARS = 1024
OUTSIDE = "a place outside the room's project folders"


class PathRefused(ToolFailure):
    """The path is not one the workbench may use. The message is for the model."""


@dataclass(frozen=True, slots=True)
class Resolved:
    real: Path
    """The real path on disk, inside the project folder."""
    rel: PurePosixPath
    """The real path relative to the project folder; `.` for the folder itself."""
    label: str
    """The folder's short name, which every path the model sees starts with."""

    @property
    def shown(self) -> str:
        """The path as the model and the owner see it."""
        return labelled(self.label, self.rel)


def labelled(label: str, rel: PurePosixPath) -> str:
    """`rel` as the model writes it: behind the folder's name."""
    return label if rel == PurePosixPath(".") else f"{label}/{rel}"


def _inside(path: Path, root: Path) -> bool:
    return path == root or path.is_relative_to(root)


class ProjectRoot:
    """One of the room's folders the workbench works in.

    `label` is the folder's short name: every path the model sees starts
    with it. The paths this class is given are already inside the folder
    (`Folders.route` took the name off).
    """

    def __init__(self, root: Path, label: str) -> None:
        real = Path(os.path.realpath(root))
        if not real.is_dir():
            raise ValueError("the project folder does not exist or is not a folder")
        home = Path(os.path.realpath(Path.home()))
        if real == Path(real.anchor) or real == home or home.is_relative_to(real):
            raise ValueError("the project folder may not be the disk, the home folder or above it")
        self.real = real
        self.label = label

    # ---- checking what the model typed -------------------------------------------------

    @staticmethod
    def parse(raw: object) -> PurePosixPath:
        if not isinstance(raw, str) or not raw.strip():
            raise PathRefused("Give a path that starts with a folder's name, for example `shop/src/app.py`, or `.`.")
        if "\x00" in raw or any(ord(ch) < 0x20 or ch == "\x7f" for ch in raw):
            raise PathRefused("The path contains control characters (such as a NUL byte); give a plain path.")
        if len(raw) > MAX_PATH_CHARS:
            raise PathRefused(f"The path is longer than {MAX_PATH_CHARS} characters.")
        if raw.startswith("~"):
            raise PathRefused(
                "Paths starting with `~` are not allowed; only the room's project folders are reachable. "
                "Give a path that starts with a folder's name."
            )
        if raw.startswith("/") or PurePosixPath(raw).is_absolute():
            raise PathRefused(
                "Absolute paths are not allowed; only the room's project folders are reachable. "
                "Give a path that starts with a folder's name, for example `shop/src/app.py`."
            )
        rel = PurePosixPath(raw)
        if ".." in rel.parts:
            raise PathRefused(f"`{raw}` uses `..`; paths may not step out of folders. Give a path from a folder's name down.")
        return rel

    def resolve(self, raw: object) -> Resolved:
        """The real path for `raw`, which must stay inside the project folder.

        Works for paths that do not exist yet: the existing part is resolved
        for real and the rest is appended, so a link anywhere along the way
        that leads out is caught.
        """
        rel = self.parse(raw)
        try:
            real = Path(os.path.realpath(self.real.joinpath(*rel.parts)))
        except (OSError, RuntimeError, ValueError):
            raise PathRefused(f"`{self.show(rel)}` could not be resolved (a link may point to itself).") from None
        if not _inside(real, self.real):
            raise PathRefused(
                f"`{self.show(rel)}` leads outside {self.where} (through a symbolic link), so it is not reachable."
            )
        return Resolved(real, PurePosixPath(real.relative_to(self.real).as_posix() or "."), self.label)

    def show(self, rel: PurePosixPath) -> str:
        """A path inside this folder as the model writes it."""
        return labelled(self.label, rel)

    @property
    def where(self) -> str:
        """This folder in words: the folder `shop`."""
        return f"the folder `{self.label}`"

    # ---- rules on top of the location ---------------------------------------------------

    def check_readable(self, raw: object) -> Resolved:
        """Resolve and refuse protected files (by the name asked for and the real name)."""
        resolved = self.resolve(raw)
        asked = self.parse(raw)
        if is_protected(asked) or is_protected(resolved.rel):
            raise PathRefused(
                f"`{self.show(asked)}` is a protected file (secrets, keys or credentials); the workbench never reads, "
                "searches or writes it. Ask the owner if its contents are needed."
            )
        return resolved

    def check_writable(self, raw: object) -> Resolved:
        """Resolve, and refuse protected files, git's own folder and git hooks."""
        resolved = self.check_readable(raw)
        asked = self.parse(raw)
        if is_git_internal(asked) or is_git_internal(resolved.rel):
            raise PathRefused(
                f"`{self.show(asked)}` is inside git's own `.git` folder, which is never written. "
                "Use git commands (with run_program) for history and settings."
            )
        if self._is_hook(asked) or self._is_hook(resolved.rel):
            raise PathRefused(f"`{self.show(asked)}` is in a git hooks folder; hooks are never created or changed.")
        if resolved.rel == PurePosixPath("."):
            raise PathRefused(f"That is {self.where} itself, not a file.")
        return resolved

    def _is_hook(self, rel: PurePosixPath) -> bool:
        folded = [part.casefold() for part in rel.parts]
        if any(part in HOOK_FOLDERS for part in folded[:-1]):
            return True
        hooks = self._hooks_path()
        if hooks is None:
            return False
        rel_c, hooks_c = PurePosixPath(str(rel).casefold()), PurePosixPath(str(hooks).casefold())
        return rel_c == hooks_c or rel_c.is_relative_to(hooks_c)

    def _hooks_path(self) -> PurePosixPath | None:
        """`core.hooksPath` from the project's git settings, when it points inside the project."""
        config = self.real / ".git" / "config"
        try:
            if config.is_symlink() or not config.is_file() or config.stat().st_size > 256_000:
                return None
            parser = configparser.ConfigParser(strict=False, interpolation=None)
            parser.read_string(config.read_text(errors="replace"))
            value = parser.get("core", "hookspath", fallback=None)
        except (OSError, configparser.Error):
            return None
        if not value:
            return None
        target = Path(os.path.realpath(self.real / os.path.expanduser(value.strip().strip('"'))))
        if not target.is_relative_to(self.real):
            return None
        return PurePosixPath(target.relative_to(self.real).as_posix())

    def relative_name(self, real: Path) -> str:
        """`real` as a project-relative path, or a neutral phrase when it is outside."""
        if _inside(real, self.real):
            return self.show(PurePosixPath(real.relative_to(self.real).as_posix() or "."))
        return OUTSIDE
