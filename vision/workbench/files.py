"""Listing, reading, writing and editing files inside one of the room's project folders.

Blocking file work; the tools run these in a thread. Every function takes
the raw arguments the model gave and raises `ToolFailure` (or `PathRefused`)
with words the model can act on.
"""

from __future__ import annotations

import os
import stat
import tempfile
import unicodedata
from pathlib import Path, PurePosixPath

from vision.gate.tools import ToolFailure
from vision.workbench.paths import OUTSIDE, PathRefused, ProjectRoot, Resolved
from vision.workbench.protected import is_protected_name

# ---- limits ---------------------------------------------------------------------------

DEFAULT_LIST_DEPTH = 2
MAX_LIST_DEPTH = 6
MAX_LIST_ENTRIES = 400

MAX_READ_FILE_BYTES = 10_000_000
"""Files larger than this are not read at all (search them instead)."""
DEFAULT_READ_LINES = 2000
MAX_READ_CHARS = 60_000
MAX_LINE_CHARS = 2000
BINARY_SNIFF_BYTES = 8192

MAX_WRITE_BYTES = 1_000_000
MAX_EDIT_FILE_BYTES = 2_000_000
PREVIEW_LINES = 40
PREVIEW_CHARS = 3000

# Folders not walked into while listing or searching: version control,
# dependencies, virtual environments, build output and caches. They are
# shown as skipped, and can still be listed by naming them.
SKIPPED_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "bower_components",
        ".venv",
        "venv",
        ".tox",
        ".nox",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".cache",
        "dist",
        "build",
        ".build",
        "target",
        "out",
        ".next",
        ".nuxt",
        ".svelte-kit",
        ".turbo",
        ".parcel-cache",
        ".expo",
        ".gradle",
        "DerivedData",
        "Pods",
        "coverage",
        ".idea",
    }
)


def is_skipped_dir(path: Path, name: str) -> bool:
    """A folder the walkers do not enter (by name, or a virtual environment by its marker)."""
    return name in SKIPPED_DIRS or name.endswith(".egg-info") or (path / "pyvenv.cfg").is_file()


def human_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    value = float(size)
    for unit in ("KB", "MB", "GB"):
        value /= 1024
        if value < 1024 or unit == "GB":
            break
    return f"{value:.1f} {unit}"


# ---- list_files -----------------------------------------------------------------------


def list_depth(raw_depth: object) -> int:
    return _int_arg(raw_depth, "depth", DEFAULT_LIST_DEPTH, 1, MAX_LIST_DEPTH)


def list_files(root: ProjectRoot, raw_path: object = ".", raw_depth: object = DEFAULT_LIST_DEPTH) -> str:
    resolved = root.check_readable(raw_path if raw_path not in (None, "") else ".")
    depth = list_depth(raw_depth)
    if not resolved.real.is_dir():
        if resolved.real.exists():
            raise ToolFailure(f"`{resolved.shown}` is a file, not a folder; use read_file to read it.")
        raise ToolFailure(f"`{resolved.shown}` does not exist.")

    lines: list[str] = []
    cut = False

    def walk(folder: Path, rel: PurePosixPath, level: int) -> None:
        nonlocal cut
        try:
            with os.scandir(folder) as it:
                entries = sorted(it, key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.casefold()))
        except OSError:
            lines.append(f"{'  ' * level}(could not open this folder)")
            return
        for entry in entries:
            if len(lines) >= MAX_LIST_ENTRIES:
                cut = True
                return
            indent = "  " * level
            entry_rel = rel / entry.name
            if entry.is_symlink():
                lines.append(f"{indent}{entry.name} -> {_link_target(root, Path(entry.path))}")
                continue
            if is_protected_name(entry.name):
                kind = "/" if entry.is_dir(follow_symlinks=False) else ""
                lines.append(f"{indent}{entry.name}{kind}  [protected: secrets, never read]")
                continue
            if entry.is_dir(follow_symlinks=False):
                if is_skipped_dir(Path(entry.path), entry.name):
                    lines.append(f"{indent}{entry.name}/  [skipped: dependencies, build output or cache]")
                elif level + 1 < depth:
                    lines.append(f"{indent}{entry.name}/")
                    walk(Path(entry.path), entry_rel, level + 1)
                else:
                    lines.append(f"{indent}{entry.name}/  [not expanded]")
                continue
            try:
                size = human_size(entry.stat(follow_symlinks=False).st_size)
            except OSError:
                size = "?"
            lines.append(f"{indent}{entry.name}  ({size})")

    walk(resolved.real, resolved.rel, 0)
    header = f"{resolved.shown}/ (depth {depth})"
    if not lines:
        return f"{header}\n(empty)"
    body = "\n".join(lines)
    if cut:
        body += (
            f"\n[cut at {MAX_LIST_ENTRIES} entries; list a subfolder with list_files(path=...) "
            "or a smaller depth to see the rest]"
        )
    return f"{header}\n{body}"


def _link_target(root: ProjectRoot, link: Path) -> str:
    """Where a link leads, without naming anything outside the project."""
    try:
        real = Path(os.path.realpath(link))
    except (OSError, RuntimeError, ValueError):
        return "(broken link)"
    if not real.exists():
        return "(broken link)"
    name = root.relative_name(real)
    if name == OUTSIDE:
        return "(link that leads outside the project; not followed)"
    return f"{name}  (link, not followed)"


# ---- read_file ------------------------------------------------------------------------


def _open_regular(resolved: Resolved) -> tuple[int, os.stat_result]:
    """Open a regular file without following a link swapped in at the last moment."""
    try:
        fd = os.open(resolved.real, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        raise ToolFailure(f"`{resolved.shown}` does not exist.") from None
    except IsADirectoryError:
        raise ToolFailure(f"`{resolved.shown}` is a folder; use list_files to see inside it.") from None
    except OSError:
        raise ToolFailure(f"`{resolved.shown}` could not be opened.") from None
    info = os.fstat(fd)
    if stat.S_ISDIR(info.st_mode):
        os.close(fd)
        raise ToolFailure(f"`{resolved.shown}` is a folder; use list_files to see inside it.")
    if not stat.S_ISREG(info.st_mode):
        os.close(fd)
        raise ToolFailure(f"`{resolved.shown}` is not a regular file (a pipe, socket or device).")
    return fd, info


def _read_bytes(resolved: Resolved, limit: int, what: str) -> bytes:
    fd, info = _open_regular(resolved)
    with os.fdopen(fd, "rb") as handle:
        if info.st_size > limit:
            raise ToolFailure(
                f"`{resolved.shown}` is {human_size(info.st_size)}, more than the {human_size(limit)} "
                f"{what} handles. Use search_files to find the part you need."
            )
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise ToolFailure(f"`{resolved.shown}` is larger than the {human_size(limit)} {what} handles.")
    return data


def _refuse_binary(resolved: Resolved, data: bytes) -> None:
    if b"\x00" in data[:BINARY_SNIFF_BYTES]:
        raise ToolFailure(f"`{resolved.shown}` is a binary file; only text files can be read or edited.")


def read_file(root: ProjectRoot, raw_path: object, raw_start: object = None, raw_end: object = None) -> str:
    resolved = root.check_readable(raw_path)
    data = _read_bytes(resolved, MAX_READ_FILE_BYTES, "read_file")
    _refuse_binary(resolved, data)
    text = data.decode("utf-8", errors="replace")
    all_lines = text.splitlines()
    total = len(all_lines)
    if total == 0:
        return f"{resolved.shown}: empty file"

    start = _int_arg(raw_start, "start_line", 1, 1, None)
    if start > total:
        raise ToolFailure(f"`{resolved.shown}` has only {total} lines; start_line {start} is past the end.")
    default_end = min(total, start + DEFAULT_READ_LINES - 1)
    end = _int_arg(raw_end, "end_line", default_end, start, None)
    end = min(end, total)

    width = len(str(end))
    out: list[str] = []
    used = 0
    last = start - 1
    for number in range(start, end + 1):
        line = all_lines[number - 1]
        if len(line) > MAX_LINE_CHARS:
            line = line[:MAX_LINE_CHARS] + f" [line cut at {MAX_LINE_CHARS} characters]"
        rendered = f"{number:>{width}}\t{line}"
        if used + len(rendered) + 1 > MAX_READ_CHARS and out:
            break
        out.append(rendered)
        used += len(rendered) + 1
        last = number

    header = f"{resolved.shown}: lines {start}-{last} of {total}"
    body = "\n".join(out)
    if last < total:
        reason = "the size cap" if last < end else "the default range"
        body += (
            f"\n[cut after line {last} of {total} ({reason}); call read_file with "
            f"start_line={last + 1} to read on]"
        )
    return f"{header}\n{body}"


# ---- write_file -----------------------------------------------------------------------


def _text_content(raw: object, name: str, *, allow_empty: bool = True) -> str:
    if not isinstance(raw, str):
        raise ToolFailure(f"`{name}` must be a string.")
    if not allow_empty and raw == "":
        raise ToolFailure(f"`{name}` must not be empty.")
    if "\x00" in raw:
        raise ToolFailure(f"`{name}` contains a NUL byte; only text can be written.")
    return raw


def _line_count(text: str) -> int:
    return len(text.splitlines())


def _existing_lines(resolved: Resolved) -> int | None:
    """Line count of the file being replaced; None when it does not exist."""
    if not resolved.real.exists():
        return None
    try:
        data = _read_bytes(resolved, MAX_EDIT_FILE_BYTES, "the workbench")
    except ToolFailure:
        return -1
    return data.count(b"\n") + (0 if data.endswith(b"\n") or not data else 1)


def _make_parents(root: ProjectRoot, resolved: Resolved) -> None:
    """Create missing folders between the room's folder and the file, all inside it."""
    parent_rel = resolved.rel.parent
    current = root.real
    for part in parent_rel.parts:
        current = current / part
        if current.is_symlink() or (current.exists() and not current.is_dir()):
            # resolve() already followed every existing link; anything odd here changed under us.
            raise ToolFailure(f"`{parent_rel}` is not a folder; the file cannot be created there.")
        if not current.exists():
            try:
                current.mkdir()
            except FileExistsError:
                pass
            except OSError:
                raise ToolFailure(f"The folder `{root.relative_name(current)}` could not be created.") from None
    real_parent = Path(os.path.realpath(resolved.real.parent))
    if real_parent != root.real and not real_parent.is_relative_to(root.real):
        raise PathRefused(f"`{resolved.shown}` leads outside {root.where}, so it is not reachable.")


def _atomic_write(root: ProjectRoot, resolved: Resolved, data: bytes) -> None:
    """Write through a temporary file in the same folder and a rename."""
    _make_parents(root, resolved)
    mode = 0o644
    try:
        current = os.lstat(resolved.real)
    except FileNotFoundError:
        current = None
    if current is not None:
        if stat.S_ISDIR(current.st_mode):
            raise ToolFailure(f"`{resolved.shown}` is a folder; give a file path.")
        if not stat.S_ISREG(current.st_mode):
            raise ToolFailure(f"`{resolved.shown}` is not a regular file and cannot be replaced.")
        mode = stat.S_IMODE(current.st_mode) & 0o777
    fd, tmp = tempfile.mkstemp(prefix=f".{resolved.real.name}.", suffix=".tmp", dir=resolved.real.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, resolved.real)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_file(root: ProjectRoot, raw_path: object, raw_content: object) -> str:
    resolved = root.check_writable(raw_path)
    content = _text_content(raw_content, "content")
    data = content.encode("utf-8")
    if len(data) > MAX_WRITE_BYTES:
        raise ToolFailure(
            f"The content is {human_size(len(data))}, more than the {human_size(MAX_WRITE_BYTES)} "
            "write_file accepts. Split it into smaller files."
        )
    before = _existing_lines(resolved)
    try:
        _atomic_write(root, resolved, data)
    except OSError:
        raise ToolFailure(f"`{resolved.shown}` could not be written.") from None
    lines = _line_count(content)
    if before is None:
        return f"Created {resolved.shown} ({lines} lines)."
    return f"Replaced {resolved.shown} (now {lines} lines)."


def describe_write(root: ProjectRoot, args: dict[str, object]) -> str:
    try:
        resolved = root.check_writable(args.get("path"))
        content = _text_content(args.get("content"), "content")
    except ToolFailure as exc:
        return f"This request will be refused: {exc}"
    lines = _line_count(content)
    before = _existing_lines(resolved)
    if before is None:
        head = f"Create new file {resolved.shown} ({lines} lines)"
    elif before < 0:
        head = f"Replace {resolved.shown} (a large or unreadable file) with {lines} lines"
    else:
        head = f"Replace {resolved.shown} ({before} lines) with {lines} lines"
    return f"{head}, in the folder {root.real}.\n\n{preview(content)}"


# ---- edit_file ------------------------------------------------------------------------


def _edit_plan(root: ProjectRoot, args: dict[str, object]) -> tuple[Resolved, str, str, str]:
    resolved = root.check_writable(args.get("path"))
    old = _text_content(args.get("old"), "old", allow_empty=False)
    new = _text_content(args.get("new"), "new")
    if old == new:
        raise ToolFailure("`old` and `new` are the same; nothing would change.")
    data = _read_bytes(resolved, MAX_EDIT_FILE_BYTES, "edit_file")
    _refuse_binary(resolved, data)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ToolFailure(
            f"`{resolved.shown}` is not UTF-8 text, so it is not edited (that could damage it)."
        ) from None
    first = text.find(old)
    if first < 0:
        raise ToolFailure(
            f"`old` was not found in {resolved.shown}. Read the file again and copy the text exactly, "
            "including spaces and line breaks."
        )
    if text.find(old, first + 1) >= 0:
        count = text.count(old)
        raise ToolFailure(
            f"`old` appears more than once in {resolved.shown} ({max(count, 2)} times); include more "
            "surrounding lines so it matches exactly one place."
        )
    return resolved, text[:first] + new + text[first + len(old) :], old, new


def edit_file(root: ProjectRoot, args: dict[str, object]) -> str:
    resolved, updated, old, new = _edit_plan(root, args)
    data = updated.encode("utf-8")
    if len(data) > MAX_EDIT_FILE_BYTES:
        raise ToolFailure(f"The edited file would be larger than {human_size(MAX_EDIT_FILE_BYTES)}.")
    try:
        _atomic_write(root, resolved, data)
    except OSError:
        raise ToolFailure(f"`{resolved.shown}` could not be written.") from None
    return f"Edited {resolved.shown}: replaced {_line_count(old) or 1} line(s) with {_line_count(new)} line(s)."


def describe_edit(root: ProjectRoot, args: dict[str, object]) -> str:
    try:
        resolved, _updated, old, new = _edit_plan(root, args)
    except ToolFailure as exc:
        return f"This request will be refused: {exc}"
    return (
        f"Edit {resolved.shown}, in the folder {root.real}.\n\n"
        f"Replace:\n{preview(old)}\n\nWith:\n{preview(new) if new else '(nothing: the text is removed)'}"
    )


# ---- shared helpers -------------------------------------------------------------------


def visible(text: str) -> str:
    """Text with invisible and control characters shown as escapes, so a card cannot hide anything."""
    out = []
    for ch in text:
        if ch in "\n\t":
            out.append(ch)
        elif ord(ch) < 0x20 or ord(ch) == 0x7F or unicodedata.category(ch) in ("Cf", "Cc", "Zl", "Zp"):
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    return "".join(out)


def preview(text: str) -> str:
    lines = text.splitlines()
    shown = lines[:PREVIEW_LINES]
    body = "\n".join(shown)
    cut = len(lines) > PREVIEW_LINES
    if len(body) > PREVIEW_CHARS:
        body = body[:PREVIEW_CHARS]
        cut = True
    body = visible(body)
    if cut:
        rest = max(len(lines) - len(body.splitlines()), 0)
        body += f"\n… ({rest} more lines not shown)" if rest else "\n… (cut)"
    return body


def _int_arg(raw: object, name: str, default: int, low: int, high: int | None) -> int:
    if raw is None:
        return default
    if isinstance(raw, bool) or not isinstance(raw, int):
        if isinstance(raw, float) and raw.is_integer():
            raw = int(raw)
        else:
            raise ToolFailure(f"`{name}` must be a whole number.")
    if raw < low:
        raise ToolFailure(f"`{name}` must be at least {low}.")
    if high is not None and raw > high:
        raise ToolFailure(f"`{name}` may be at most {high}.")
    return raw
