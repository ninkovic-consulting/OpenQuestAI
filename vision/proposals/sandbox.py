"""Confinement for the tools agents write: a macOS `sandbox-exec` profile per run.

An agent's script becomes a tool once the owner approves it, but approval
rests on a person reading code. The confinement is the part that does not:
macOS itself refuses what the profile does not allow, whatever the script
says. It uses only what every Mac has (`/usr/bin/sandbox-exec`, the sandbox
calls in libSystem), so it needs no new permission and no new dependency.

How a run is confined:
- the profile starts from "deny everything", imports Apple's `system.sb`
  (without it not even `/bin/echo` starts), then allows reading the system,
  the Python runtime and the approved folders, and writing only the run's
  scratch folder. Denials come after the allows because in a sandbox profile
  the last matching rule wins: the assistant's home, the owner's key and
  login folders and the workbench's protected file names are denied even
  inside an approved folder, and the scratch is allowed again last;
- paths never become profile text: each goes in as a `-D` parameter that the
  profile names with `(param ...)`, so a folder name cannot change the rules;
- the network, sockets on this Mac, the Keychain, the pasteboard, Apple
  Events and opening apps stay closed because nothing allows them, and only
  the Mach services `system.sb` itself allows can be looked up;
- a small launcher sets resource limits (CPU seconds, the size of one file,
  open files, new processes) before `sandbox-exec` starts, so a script cannot
  fill the disk through its scratch folder or start processes without end.

A shell needs `fork`, so a script can leave a detached process behind that
escapes its process group. Such leftovers are found by asking the sandbox
about every process of this user. Each run gets two empty marker files with
random names beside its scratch folder; its profile allows reading one and
denies the other. A process belongs to this run when the sandbox lets it
read the first and not the second: unconfined processes may read both,
other runs and other sandboxed apps (whose rules cannot tell two random
names apart) are given the same answer for both. The files must exist,
because for a missing path the sandbox answers "denied" even for an
unconfined process. Leftovers are killed when the run ends, however it ends.

When any of this is unavailable the run is refused (`Unavailable`); it never
falls back to running unconfined.
"""

from __future__ import annotations

import asyncio
import ctypes
import functools
import math
import os
import secrets
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Literal

from vision.gate.tools import run_command
from vision.workbench import protected
from vision.workbench.programs import clean_environment

Language = Literal["python", "sh"]

SANDBOX_EXEC = "/usr/bin/sandbox-exec"
MAX_FILE_BYTES = 64 * 1024 * 1024
"""The largest single file a run may write."""
MAX_OPEN_FILES = 256
MORE_PROCESSES = 64
"""How many processes a run may have at once beyond what the user already runs."""
_SWEEP_ROUNDS = 20

_LIBSYSTEM = "/usr/lib/libSystem.B.dylib"
_SANDBOX_FILTER_PATH = 1
_SANDBOX_CHECK_NO_REPORT = 0x40000000
_PROC_UID_ONLY = 4

# Folders and files under the owner's home where keys, tokens and logins
# live. Denied in every run, even when an approved folder contains them.
_SECRET_HOME_PATHS = (
    ".ssh",
    ".aws",
    ".azure",
    ".gnupg",
    ".config",
    ".kube",
    ".docker",
    ".netrc",
    ".npmrc",
    ".pypirc",
    ".git-credentials",
    ".gitconfig",
    ".zsh_history",
    ".bash_history",
    "Library/Keychains",
    "Library/Cookies",
    "Library/Application Support/com.apple.TCC",
)

# Runs the child after setting its resource limits; it then execs
# `sandbox-exec`, so the limits hold for every process of the run.
_LAUNCHER = """\
import os, resource, sys
cpu, fsize, nproc, nofile = map(int, sys.argv[1:5])
for kind, soft, hard in (
    (resource.RLIMIT_CPU, cpu, cpu + 1),
    (resource.RLIMIT_FSIZE, fsize, fsize),
    (resource.RLIMIT_CORE, 0, 0),
    (resource.RLIMIT_NOFILE, nofile, nofile),
    (resource.RLIMIT_NPROC, nproc, nproc),
):
    resource.setrlimit(kind, (soft, hard))
os.execv(sys.argv[5], sys.argv[5:])
"""

ENFORCED: tuple[str, ...] = (
    "macOS itself confines every run with a sandbox; where it cannot, the tool does not run at all.",
    "The script can write only in its own empty scratch folder, which is deleted after the run.",
    (
        "It can read only macOS system files, the Python runtime, its scratch folder and the folders "
        "you approved for it, and those only for reading."
    ),
    (
        "It cannot read the assistant's own folder, your SSH, cloud, GPG, Docker and Kubernetes keys, "
        "~/.config, your Keychains and cookies, or protected files (.env files, private keys, credential "
        "and secrets files) inside the approved folders."
    ),
    (
        "Without network approval it cannot open any network connection, not even to this Mac. "
        "With it, it can only connect out; it can never listen for connections."
    ),
    (
        "It cannot reach the Keychain, the clipboard, other apps (no Apple Events, no opening apps) "
        "or local services through their sockets."
    ),
    (
        "It gets no secrets in its environment: a minimal PATH, its input on stdin and the list of its "
        "folders in FOLDERS."
    ),
    (
        "It is stopped at its time limit, and its CPU time, the size of each file it writes, its open "
        "files and the number of processes it can start are capped."
    ),
    "Any process it leaves behind, even a detached one, is found and killed when the run ends.",
)

NOT_ENFORCED: tuple[str, ...] = (
    "What the script does with what it may read: it can print any of it back to the agent.",
    (
        "With network approval, where it connects: any address on the internet or your network, "
        "so it could send what it read anywhere."
    ),
    "Memory is not capped, nor the scratch folder as a whole (only each file in it).",
    (
        "It can see whether a file exists and its size and dates almost anywhere on the disk; only "
        "reading contents is confined."
    ),
    "It can read the system's own files like any program, for example the list of user accounts.",
    "Timing and other side channels, and flaws in macOS itself, are beyond this confinement.",
    (
        "Apple marks sandbox-exec as deprecated. It works on this macOS; if a future macOS removes "
        "it, made tools stop running rather than run unconfined."
    ),
)


@dataclass(frozen=True, slots=True)
class Reach:
    read: tuple[Path, ...]
    """Folders the script may read (never write)."""
    network: bool


@dataclass(frozen=True, slots=True)
class RunResult:
    exit_code: int | None
    """None when the run was stopped at the timeout."""
    output: str
    truncated: bool
    seconds: float
    swept: int
    """Leftover processes of this run killed after it ended."""


class Unavailable(Exception):
    """macOS cannot confine the run here; the run is refused, never run unconfined."""


# --- The protected file names, as one sandbox regex -------------------------
#
# The workbench matches every path component against shell-style patterns,
# ignoring case, except for the committed templates `.env.example` and
# `.env.sample`. A sandbox regex has no "ignore case" and no "except", so
# each letter becomes a class of both cases and a pattern that would also
# match an allowed name becomes its literal prefix followed by "anything but
# those endings". The construction refuses patterns it cannot translate
# faithfully, so a new pattern in `protected` fails loudly here. A string in
# a profile holds at most 1,023 characters, so the alternatives are split
# over several regexes.

_REGEX_MAX = 1000


def _letter(char: str) -> str:
    if char.isascii() and char.isalpha():
        return f"[{char.lower()}{char.upper()}]"
    if char.isascii() and char.isdigit():
        return char
    if char in "]\\^\n\"":
        raise ValueError(f"cannot put {char!r} in a sandbox regex")
    return f"[{char}]"


def _class_members(char: str) -> str:
    if char.isascii() and char.isalnum():
        return char.lower() + char.upper() if char.isalpha() else char
    if char in "]\\^-\n\"":
        raise ValueError(f"cannot put {char!r} in a sandbox regex class")
    return char


def _pattern(pattern: str) -> str:
    if any(c in pattern for c in "?["):
        raise ValueError(f"cannot translate the protected pattern {pattern!r}")
    return "".join("[^/]*" if c == "*" else _letter(c) for c in pattern)


def _none_of(words: Sequence[str]) -> str:
    """A regex for any name part (no `/`) that is none of `words`, ignoring case."""
    trie: dict[str, dict[str, Any]] = {}
    for word in words:
        node = trie
        for char in word.casefold():
            node = node.setdefault(char, {})
        node[""] = {}

    def walk(node: dict[str, Any]) -> str:
        kids = sorted(char for char in node if char)
        others = "".join(_class_members(char) for char in kids)
        branches = [f"[^/{others}][^/]*"] + [_letter(char) + walk(node[char]) for char in kids]
        body = "(" + "|".join(branches) + ")"
        return body if "" in node else body + "?"

    return walk(trie)


def _protected_regexes() -> tuple[str, ...]:
    alternatives: list[str] = []
    for pattern in protected._PATTERNS:
        spared = [name for name in protected._ENV_ALLOWED if fnmatchcase(name, pattern)]
        if not spared:
            alternatives.append(_pattern(pattern))
            continue
        prefix = pattern[:-1]
        if not pattern.endswith("*") or "*" in prefix or not all(n.startswith(prefix) for n in spared):
            raise ValueError(f"cannot translate the protected pattern {pattern!r}")
        alternatives.append(_pattern(prefix) + _none_of([n[len(prefix) :] for n in spared]))
    regexes: list[str] = []
    group: list[str] = []
    for alternative in alternatives:
        if group and len(_component("|".join([*group, alternative]))) > _REGEX_MAX:
            regexes.append(_component("|".join(group)))
            group = []
        group.append(alternative)
    regexes.append(_component("|".join(group)))
    if any(len(regex) > _REGEX_MAX for regex in regexes):
        raise ValueError("a protected pattern is too long for a sandbox regex")
    return tuple(regexes)


def _component(alternatives: str) -> str:
    return f"/({alternatives})(/|$)"


PROTECTED_REGEXES = _protected_regexes()
"""A path matches one of these when any component is a name the workbench protects
(`vision.workbench.protected`)."""


# --- The profile --------------------------------------------------------------

_SYSTEM_READ = (
    "/bin",
    "/usr/bin",
    "/usr/libexec",
    "/usr/sbin",
    "/sbin",
    "/private/var/select",
)
_NETWORK_READ = ("/private/etc/hosts", "/private/etc/resolv.conf", "/private/var/run/resolv.conf")


def _profile(*, readable: int, denied: int, network: bool) -> str:
    """The profile text. Every path in it is a `(param ...)`; the rest is fixed."""
    lines = [
        "(version 1)",
        "(deny default)",
        '(import "system.sb")',
        "(allow process-exec process-fork)",
        "(allow signal (target same-sandbox))",
        "(allow file-read-metadata)",
        "(allow file-read* " + " ".join(f'(subpath "{path}")' for path in _SYSTEM_READ) + ")",
        '(allow file-read* file-map-executable (subpath (param "PYTHON_PREFIX")))',
        '(allow file-read* file-map-executable (literal (param "PYTHON")))',
    ]
    if network:
        lines += [
            "(system-network)",
            "(allow file-read* " + " ".join(f'(literal "{path}")' for path in _NETWORK_READ) + ")",
            "(allow network-outbound (remote ip))",
            '(allow network-outbound (literal "/private/var/run/mDNSResponder"))',
        ]
    for n in range(readable):
        lines.append(f'(allow file-read* (subpath (param "READ{n}")))')
    protected_names = "(require-any " + " ".join(f'(regex #"{regex}")' for regex in PROTECTED_REGEXES) + ")"
    for n in range(readable):
        lines.append(f'(deny file-read* file-write* (require-all (subpath (param "READ{n}")) {protected_names}))')
    for n in range(denied):
        lines.append(f'(deny file-read* file-write* (subpath (param "DENY{n}")))')
    lines += [
        '(allow file-read* file-write* (subpath (param "SCRATCH")))',
        '(allow file-read* (literal (param "MARK_READ")))',
        '(deny file-read* file-write* (literal (param "MARK_DENIED")))',
    ]
    return "\n".join(lines) + "\n"


def _secret_paths(home: Path) -> list[Path]:
    return [home / rel for rel in _SECRET_HOME_PATHS]


def _real(path: Path) -> str:
    return os.path.realpath(path)


def _python() -> tuple[str, str]:
    """The real interpreter and its prefix (`/usr/bin/python3` is only Xcode's shim)."""
    executable = getattr(sys, "_base_executable", sys.executable)  # outside any virtual environment
    return os.path.realpath(executable), os.path.realpath(sys.base_prefix)


@dataclass(frozen=True, slots=True)
class _Marks:
    """The two marker files that tell this run's processes from all others."""

    read: str
    denied: str

    @classmethod
    def beside(cls, scratch: str) -> _Marks:
        stem = f"{scratch}.{secrets.token_hex(8)}"
        marks = cls(read=stem + ".r", denied=stem + ".d")
        for path in (marks.read, marks.denied):
            os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400))
        return marks

    def remove(self) -> None:
        for path in (self.read, self.denied):
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass


def _argv(
    language: Language, script: str, *, reach: Reach, scratch: str, marks: _Marks, deny: Sequence[Path], cpu: int
) -> list[str]:
    python, prefix = _python()
    readable = [_real(path) for path in reach.read]
    denied = [_real(path) for path in deny]
    params = {"PYTHON": python, "PYTHON_PREFIX": prefix, "SCRATCH": scratch}
    params |= {"MARK_READ": marks.read, "MARK_DENIED": marks.denied}
    params |= {f"READ{n}": path for n, path in enumerate(readable)}
    params |= {f"DENY{n}": path for n, path in enumerate(denied)}
    profile = _profile(readable=len(readable), denied=len(denied), network=reach.network)
    command = [python, "-I", "-S", "-B", "-c", script] if language == "python" else ["/bin/sh", "-c", script]
    nproc = len(_user_pids()) + MORE_PROCESSES
    limits = [str(cpu), str(MAX_FILE_BYTES), str(nproc), str(MAX_OPEN_FILES)]
    defines = [arg for name, value in params.items() for arg in ("-D", f"{name}={value}")]
    return [python, "-I", "-S", "-B", "-c", _LAUNCHER, *limits, SANDBOX_EXEC, "-p", profile, *defines, *command]


# --- Finding leftovers ----------------------------------------------------------


@functools.cache
def _libsystem() -> ctypes.CDLL:
    lib = ctypes.CDLL(_LIBSYSTEM, use_errno=True)
    # The path is the variadic argument; on arm64 it must not be declared.
    lib.sandbox_check.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    lib.sandbox_check.restype = ctypes.c_int
    lib.proc_listpids.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_int]
    lib.proc_listpids.restype = ctypes.c_int
    return lib


def _user_pids() -> list[int]:
    lib = _libsystem()
    uid = os.getuid()
    size = lib.proc_listpids(_PROC_UID_ONLY, uid, None, 0)
    if size <= 0:
        return []
    count = size // ctypes.sizeof(ctypes.c_int) + 64
    buffer = (ctypes.c_int * count)()
    used = lib.proc_listpids(_PROC_UID_ONLY, uid, buffer, ctypes.sizeof(buffer))
    return [pid for pid in buffer[: max(used, 0) // ctypes.sizeof(ctypes.c_int)] if pid > 0]


def _may_read(pid: int, path: str) -> int:
    """0 allowed, 1 denied, anything else unknown (the process is gone, say)."""
    flags = _SANDBOX_FILTER_PATH | _SANDBOX_CHECK_NO_REPORT
    return int(_libsystem().sandbox_check(pid, b"file-read-data", flags, ctypes.c_char_p(os.fsencode(path))))


def _of_this_run(pid: int, marks: _Marks) -> bool:
    return _may_read(pid, marks.read) == 0 and _may_read(pid, marks.denied) == 1


def _sweep(marks: _Marks) -> int:
    """Kill every process confined by this run's profile; how many were killed."""
    if not (os.path.isfile(marks.read) and os.path.isfile(marks.denied)):
        return 0  # Without both files every process would look like this run's.
    spared = {os.getpid(), os.getppid()}
    killed: set[int] = set()
    for _ in range(_SWEEP_ROUNDS):
        found = [pid for pid in _user_pids() if pid not in spared | killed and _of_this_run(pid, marks)]
        if not found:
            break
        for pid in found:
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                spared.add(pid)
                continue
            killed.add(pid)
    return len(killed)


# --- Availability ---------------------------------------------------------------


@functools.cache
def problem() -> str | None:
    """Why runs cannot be confined here, or None. Checked once, by a real confined run."""
    if sys.platform != "darwin":
        return "Made tools run only on a Mac, where macOS can confine them."
    if not os.access(SANDBOX_EXEC, os.X_OK):
        return "This Mac has no /usr/bin/sandbox-exec, so made tools cannot be confined and do not run."
    try:
        _libsystem()
    except (OSError, AttributeError):
        return "This Mac lacks the sandbox calls made tools need to find leftover processes, so they do not run."
    with tempfile.TemporaryDirectory(prefix="vision-sandbox-check-") as base:
        root = Path(os.path.realpath(base))
        scratch, outside = root / "scratch", root / "outside"
        scratch.mkdir()
        outside.mkdir()
        marks = _Marks.beside(str(scratch))
        script = "echo inside > inside; echo outside > ../outside/leak 2>/dev/null; exit 0"
        argv = _argv(
            "sh", script, reach=Reach(read=(), network=False), scratch=str(scratch), marks=marks, deny=(), cpu=10
        )
        try:
            done = subprocess.run(
                argv,
                cwd=scratch,
                env=_environment(scratch, {}),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            done = None
        confined = (
            done is not None
            and done.returncode == 0
            and (scratch / "inside").is_file()
            and not (outside / "leak").exists()
        )
    if not confined:
        return "macOS did not confine a test run here (sandbox-exec failed), so made tools do not run."
    return None


def _environment(scratch: Path, extra: Mapping[str, str]) -> dict[str, str]:
    env = clean_environment({})
    env["HOME"] = str(scratch)
    env["TMPDIR"] = str(scratch)
    for name, value in extra.items():
        if "=" in name or "\x00" in name or "\x00" in value:
            raise ValueError(f"environment variable {name!r} cannot be passed to a process")
        env[name] = value
    return env


async def run_confined(
    language: Language,
    script: str,
    stdin: bytes,
    *,
    reach: Reach,
    scratch: Path,
    deny: Sequence[Path],
    env_extra: Mapping[str, str],
    timeout: float,
    limit: int,
) -> RunResult:
    """Run `script` confined by macOS, in `scratch` (which must exist), and kill what it leaves behind.

    Raises `Unavailable` when confinement is not possible here, and
    `ValueError` for a script or environment that cannot be passed to a
    process (a NUL byte).
    """
    reason = await asyncio.to_thread(problem)
    if reason is not None:
        raise Unavailable(reason)
    if "\x00" in script:
        raise ValueError("the script contains a NUL byte")
    if not scratch.is_dir():
        raise ValueError(f"the scratch folder {scratch} does not exist")
    real_scratch = _real(scratch)
    denied = [*deny, *_secret_paths(Path.home())]
    env = _environment(Path(real_scratch), env_extra)
    marks = _Marks.beside(real_scratch)
    started = time.monotonic()
    try:
        argv = _argv(
            language,
            script,
            reach=reach,
            scratch=real_scratch,
            marks=marks,
            deny=denied,
            cpu=max(1, math.ceil(timeout)) + 1,
        )
        try:
            result = await run_command(
                argv, timeout=timeout, limit=limit, cwd=Path(real_scratch), env=env, stdin=stdin
            )
        finally:
            swept = _sweep(marks)
    finally:
        marks.remove()
    return RunResult(
        exit_code=result.returncode,
        output=result.output,
        truncated=result.truncated,
        seconds=time.monotonic() - started,
        swept=swept,
    )
