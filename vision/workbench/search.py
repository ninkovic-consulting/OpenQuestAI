"""search_files: a regular-expression search over the project's text files.

The files are chosen here (inside the project, not protected, never through
a link, skipping dependencies and caches); the matching itself runs in a
separate Python process (`_search_child.py`) under a timeout, so a pattern
that backtracks catastrophically is stopped instead of freezing the daemon.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import tempfile
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath

from vision.gate.tools import Runner, ToolFailure, run_command
from vision.workbench.files import is_skipped_dir
from vision.workbench.paths import ProjectRoot
from vision.workbench.protected import is_protected_name

MAX_PATTERN_CHARS = 500
MAX_GLOB_CHARS = 200
MAX_FILES_SCANNED = 5000
MAX_SEARCH_FILE_BYTES = 2_000_000
MAX_MATCHES = 200
MATCH_LINE_CHARS = 10_000
"""Only the first this-many characters of a line are matched (minified files)."""
SHOWN_LINE_CHARS = 300
SEARCH_TIMEOUT_S = 10.0
CHILD_OUTPUT_LIMIT = 2_000_000

_CHILD = Path(__file__).with_name("_search_child.py")


def _pattern(raw: object) -> str:
    if not isinstance(raw, str) or raw == "":
        raise ToolFailure("`pattern` must be a non-empty regular expression.")
    if "\x00" in raw:
        raise ToolFailure("`pattern` contains a NUL byte.")
    if len(raw) > MAX_PATTERN_CHARS:
        raise ToolFailure(f"`pattern` is longer than {MAX_PATTERN_CHARS} characters; use a shorter one.")
    try:
        re.compile(raw)
    except re.error as exc:
        raise ToolFailure(f"`pattern` is not a valid Python regular expression: {exc}.") from None
    return raw


def _glob(raw: object) -> str | None:
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str) or "\x00" in raw or len(raw) > MAX_GLOB_CHARS:
        raise ToolFailure(f"`glob` must be a short file pattern such as `*.py` (at most {MAX_GLOB_CHARS} characters).")
    return raw


def _glob_matches(glob: str, rel: PurePosixPath) -> bool:
    if "/" not in glob:
        return fnmatchcase(rel.name, glob)
    flat = glob.replace("**/", "*").replace("/**", "/*")
    return fnmatchcase(str(rel), flat) or fnmatchcase(str(rel), glob)


def collect_files(root: ProjectRoot, raw_path: object, glob: str | None) -> tuple[list[str], int, bool]:
    """Project-relative paths to scan, how many protected files were left out, and whether the cap cut it."""
    resolved = root.check_readable(raw_path if raw_path not in (None, "") else ".")
    if resolved.real.is_file():
        return [resolved.shown], 0, False
    if not resolved.real.is_dir():
        raise ToolFailure(f"`{resolved.shown}` does not exist.")
    files: list[str] = []
    protected = 0
    stack = [resolved.real]
    while stack:
        folder = stack.pop()
        try:
            with os.scandir(folder) as it:
                entries = sorted(it, key=lambda e: e.name)
        except OSError:
            continue
        subfolders = []
        for entry in entries:
            if entry.is_symlink():
                continue  # never followed: it may lead out of the project
            if is_protected_name(entry.name):
                protected += 1
                continue
            if entry.is_dir(follow_symlinks=False):
                if not is_skipped_dir(Path(entry.path), entry.name):
                    subfolders.append(Path(entry.path))
                continue
            if not entry.is_file(follow_symlinks=False):
                continue
            rel = PurePosixPath(Path(entry.path).relative_to(root.real).as_posix())
            if glob is not None and not _glob_matches(glob, rel):
                continue
            if len(files) >= MAX_FILES_SCANNED:
                return files, protected, True
            files.append(str(rel))
        stack.extend(reversed(subfolders))
    return files, protected, False


async def search_files(root: ProjectRoot, args: dict[str, object], *, runner: Runner = run_command) -> str:
    pattern = _pattern(args.get("pattern"))
    glob = _glob(args.get("glob"))
    ignore_case = bool(args.get("ignore_case", False))
    files, protected, capped = await asyncio.to_thread(collect_files, root, args.get("path", "."), glob)
    if not files:
        return "No files to search there" + (" match that glob." if glob else ".")

    job = {
        "root": str(root.real),
        "files": files,
        "pattern": pattern,
        "ignore_case": ignore_case,
        "max_matches": MAX_MATCHES,
        "max_file_bytes": MAX_SEARCH_FILE_BYTES,
        "match_line_chars": MATCH_LINE_CHARS,
        "shown_line_chars": SHOWN_LINE_CHARS,
    }
    fd, job_path = tempfile.mkstemp(prefix="vision-search-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(job, handle)
        result = await runner(
            [sys.executable, "-I", str(_CHILD), job_path],
            timeout=SEARCH_TIMEOUT_S,
            limit=CHILD_OUTPUT_LIMIT,
            cwd=root.real,
        )
    finally:
        try:
            os.unlink(job_path)
        except OSError:
            pass
    if result.returncode is None:
        raise ToolFailure(
            f"The search took longer than {SEARCH_TIMEOUT_S:g} seconds and was stopped. The pattern may "
            "backtrack heavily (nested repetition such as `(a+)+` or `(.*)*`); simplify it, or narrow "
            "the search with `path` or `glob`."
        )
    try:
        found = json.loads(result.output)
    except ValueError:
        raise ToolFailure("The search failed to run.") from None
    if result.returncode != 0 or result.truncated:
        raise ToolFailure("The search failed to run.")

    lines = [f"{rel}:{number}: {text}" for rel, number, text in found["matches"]]
    notes = []
    if found["more"]:
        notes.append(f"stopped at {MAX_MATCHES} matches; narrow the pattern, `path` or `glob` to see the rest")
    if capped:
        notes.append(f"only the first {MAX_FILES_SCANNED} files were searched; narrow `path` or `glob`")
    if found["too_big"]:
        notes.append(f"{found['too_big']} file(s) over {MAX_SEARCH_FILE_BYTES // 1_000_000} MB skipped")
    if found["binary"]:
        notes.append(f"{found['binary']} binary file(s) skipped")
    if protected:
        notes.append(f"{protected} protected file(s) or folder(s) not searched")
    header = f"{len(lines)} match(es) in {found['scanned']} file(s) searched."
    if not lines:
        header = f"No matches in {found['scanned']} file(s) searched."
    text = "\n".join([header, *lines])
    if notes:
        text += "\n[" + "; ".join(notes) + "]"
    return text
