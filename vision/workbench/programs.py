"""run_program: run one of the owner's allowed programs in a project folder of the room.

Be plain about what this is: a program such as `git`, `npm` or `python` can
run arbitrary code from the project (a `package.json` script, a test file, a
git hook or alias, a `setup.py`). Running one is as powerful as running a
shell command in that folder. That is why the caller always asks the owner
first, and why the card shows the exact command line and folder.

What this module does guarantee:
- only a program from the owner's list, by its id, at the absolute path the
  owner configured; never a path or name the model makes up;
- never through a shell: the arguments go to the program as they are;
- arguments are strings without NUL bytes, capped in number and length;
- the working folder is one of the room's project folders: the one named by
  `folder`, else the first;
- the child gets a clean environment (a minimal PATH, HOME, LANG and the
  like) and nothing whose name looks like a key, token, secret or password,
  never `ANTHROPIC_API_KEY` and never a `VISION_*` variable; no stdin;
- a timeout, an output cap, and the whole process group killed on timeout or
  cancellation (by `vision.gate.tools.run_command`).
"""

from __future__ import annotations

import os
import re
import shlex
from collections.abc import Mapping
from pathlib import Path

from vision.gate.tools import Runner, ToolFailure, run_command
from vision.workbench.files import visible
from vision.workbench.folders import Folders
from vision.workbench.paths import ProjectRoot

DEFAULT_TIMEOUT_S = 120.0
MAX_TIMEOUT_S = 600.0
MIN_TIMEOUT_S = 1.0
MAX_ARGS = 200
MAX_ARGS_CHARS = 32_000
OUTPUT_LIMIT = 30_000


BASE_PATH = ("/usr/bin", "/bin", "/usr/sbin", "/sbin")
_PASSED_THROUGH = ("HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR")
_SECRET_NAME = re.compile(
    r"KEY|TOKEN|SECRET|PASS|PWD|CREDENTIAL|AUTH|SESSION|COOKIE|PRIVATE|SIGNATURE|^ANTHROPIC|^VISION_|^OPENAI",
    re.IGNORECASE,
)
_PROGRAM_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")


def check_programs(programs: Mapping[str, Path]) -> dict[str, Path]:
    """The owner's program list, checked once when the tools are built."""
    checked: dict[str, Path] = {}
    for name, path in programs.items():
        if not isinstance(name, str) or not _PROGRAM_ID.match(name):
            raise ValueError(f"program id {name!r} must be a short plain name such as git or npm")
        path = Path(path)
        if not path.is_absolute():
            raise ValueError(f"the path for program {name!r} must be absolute")
        if "=" in str(path) or "\x00" in str(path):
            raise ValueError(f"the path for program {name!r} contains '=' or a NUL byte")
        checked[name] = path
    return checked


def is_secret_name(name: str) -> bool:
    return bool(_SECRET_NAME.search(name))


def clean_environment(programs: Mapping[str, Path], source: Mapping[str, str] | None = None) -> dict[str, str]:
    """The child's whole environment."""
    source = os.environ if source is None else source
    folders: list[str] = []
    for path in programs.values():
        folder = str(path.parent)
        if folder not in folders:
            folders.append(folder)
    for folder in BASE_PATH:
        if folder not in folders:
            folders.append(folder)
    env = {
        "PATH": ":".join(folders),
        "HOME": str(Path.home()),
        "LANG": "en_US.UTF-8",
        "TERM": "dumb",
        "NO_COLOR": "1",
        "PAGER": "cat",
        "GIT_PAGER": "cat",
        "GIT_TERMINAL_PROMPT": "0",
    }
    for name in _PASSED_THROUGH:
        value = source.get(name)
        if value and "\x00" not in value:
            env[name] = value
    return {name: value for name, value in env.items() if not is_secret_name(name)}


def _args(raw: object) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(isinstance(arg, str) for arg in raw):
        raise ToolFailure("`args` must be a list of strings, one per argument (no shell syntax).")
    if len(raw) > MAX_ARGS:
        raise ToolFailure(f"Too many arguments ({len(raw)}); at most {MAX_ARGS}.")
    if sum(len(arg) for arg in raw) > MAX_ARGS_CHARS:
        raise ToolFailure(f"The arguments are longer than {MAX_ARGS_CHARS} characters in all.")
    if any("\x00" in arg for arg in raw):
        raise ToolFailure("An argument contains a NUL byte.")
    return list(raw)


def _timeout(raw: object) -> float:
    if raw is None:
        return DEFAULT_TIMEOUT_S
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or raw != raw:
        raise ToolFailure("`timeout_s` must be a number of seconds.")
    return float(min(max(raw, MIN_TIMEOUT_S), MAX_TIMEOUT_S))


def quote_arg(arg: str) -> str:
    """Quote one argument the way a shell would need it, showing invisible characters as escapes."""
    if arg.isprintable() and visible(arg) == arg:
        return shlex.quote(arg)
    escaped = []
    for ch in arg:
        if ch == "\\":
            escaped.append("\\\\")
        elif ch == "'":
            escaped.append("\\'")
        elif ch == "\n":
            escaped.append("\\n")
        elif ch == "\t":
            escaped.append("\\t")
        elif ch.isprintable() and visible(ch) == ch:
            escaped.append(ch)
        else:
            escaped.append(f"\\u{ord(ch):04x}" if ord(ch) <= 0xFFFF else f"\\U{ord(ch):08x}")
    return "$'" + "".join(escaped) + "'"


class ProgramRunner:
    def __init__(self, folders: Folders, programs: Mapping[str, Path], runner: Runner = run_command) -> None:
        self.folders = folders
        self.programs = check_programs(programs)
        self.runner = runner

    def _program(self, raw: object) -> tuple[str, Path]:
        names = ", ".join(sorted(self.programs)) or "none"
        if not isinstance(raw, str) or raw not in self.programs:
            raise ToolFailure(
                f"`program` must be one of the allowed program ids: {names}. Give the id only, not a path; "
                "other programs cannot be run."
            )
        return raw, self.programs[raw]

    def plan(self, args: dict[str, object]) -> tuple[Path, list[str], float, ProjectRoot]:
        _name, path = self._program(args.get("program"))
        folder = self.folders.for_program(args.get("folder"))
        return path, _args(args.get("args")), _timeout(args.get("timeout_s")), folder

    def describe(self, args: dict[str, object]) -> str:
        try:
            path, argv, timeout, folder = self.plan(args)
        except ToolFailure as exc:
            return f"This request will be refused: {exc}"
        command = " ".join(quote_arg(part) for part in [str(path), *argv])
        return (
            f"Run this command:\n{command}\n\nIn the folder: {folder.real}\n"
            f"Stopped after {timeout:g} seconds. The program can run code from the project."
        )

    async def run(self, args: dict[str, object]) -> str:
        path, argv, timeout, folder = self.plan(args)
        if not os.path.isfile(path) or not os.access(path, os.X_OK):
            raise ToolFailure(f"The program `{args.get('program')}` is not installed where it is configured.")
        env = clean_environment(self.programs)
        result = await self.runner([str(path), *argv], timeout=timeout, limit=OUTPUT_LIMIT, cwd=folder.real, env=env)
        output = result.output.rstrip()
        if result.truncated:
            output += (
                f"\n[output cut at {OUTPUT_LIMIT} bytes; rerun with narrower arguments, or have the program "
                "write to a file in the project and read it with read_file]"
            )
        if result.returncode is None:
            raise ToolFailure(
                f"The program did not finish within {timeout:g} seconds and was stopped (with everything it "
                f"started).\n{output}".rstrip()
            )
        return f"exit code {result.returncode}\n{output}".rstrip()
