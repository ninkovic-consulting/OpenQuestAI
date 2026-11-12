"""The five tools of slice 1: remember, recall, open_app, open_url, shell.

Each tool is an async function of its arguments that returns text for the
model, or raises `ToolFailure` with a short explanation. The gate decides
whether a tool may run at all; nothing here asks the user.
"""

from __future__ import annotations

import asyncio
import os
import signal
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from vision.core.config import Config
from vision.core.interfaces import Memory, ToolSpec

DEFAULT_SHELL_TIMEOUT_S = 30.0
DEFAULT_SHELL_OUTPUT_LIMIT = 8000
OPEN_TIMEOUT_S = 10.0
OPEN_OUTPUT_LIMIT = 2000
RECALL_LIMIT = 5
RECALL_TEXT_LIMIT = 500


class ToolFailure(Exception):
    """The tool ran but could not do what was asked. The message is for the model."""


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int | None
    """None when the command was stopped at the timeout."""
    output: str
    truncated: bool


Runner = Callable[..., Awaitable[CommandResult]]


@dataclass(frozen=True, slots=True)
class Tool:
    spec: ToolSpec
    run: Callable[[dict[str, Any]], Awaitable[str]]
    summary: str
    """What the gate card says the tool wants to do."""
    detail_arg: str
    """The argument shown as the card's detail."""


async def run_command(
    argv: Sequence[str], *, timeout: float, limit: int, cwd: Path | None = None
) -> CommandResult:
    """Run a process with no stdin, capturing at most `limit` bytes of combined output.

    The process gets its own process group, which is killed on timeout or
    cancellation so nothing it started keeps running.
    """
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=cwd,
        start_new_session=True,
    )
    kept = bytearray()
    truncated = False

    async def collect() -> None:
        nonlocal truncated
        assert proc.stdout is not None
        while chunk := await proc.stdout.read(4096):
            room = limit - len(kept)
            if len(chunk) > room:
                truncated = True
            kept.extend(chunk[: max(room, 0)])
        await proc.wait()

    try:
        await asyncio.wait_for(collect(), timeout)
    except TimeoutError:
        _kill(proc)
        await proc.wait()
        return CommandResult(None, kept.decode(errors="replace"), truncated)
    except asyncio.CancelledError:
        _kill(proc)
        raise
    return CommandResult(proc.returncode, kept.decode(errors="replace"), truncated)


def _kill(proc: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _text_arg(args: dict[str, Any], name: str) -> str:
    value = args.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ToolFailure(f"`{name}` must be a non-empty string.")
    return value.strip()


def _schema(name: str, description: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {name: {"type": "string", "description": description}},
        "required": [name],
        "additionalProperties": False,
    }


def build_tools(config: Config, memory: Memory, *, runner: Runner = run_command) -> list[Tool]:
    """The tools in a fixed order (stable for prompt caching)."""
    extra = config.gate.model_extra or {}
    shell_timeout = float(extra.get("shell_timeout_s", DEFAULT_SHELL_TIMEOUT_S))
    shell_limit = int(extra.get("shell_output_limit", DEFAULT_SHELL_OUTPUT_LIMIT))

    async def remember(args: dict[str, Any]) -> str:
        await memory.remember(_text_arg(args, "text"))
        return "Noted."

    async def recall(args: dict[str, Any]) -> str:
        hits = await memory.recall(_text_arg(args, "query"), RECALL_LIMIT)
        if not hits:
            return "Nothing found."
        lines = []
        for hit in hits:
            day = time.strftime("%Y-%m-%d", time.localtime(hit.ts))
            lines.append(f"- [{hit.kind}, {day}] {hit.text[:RECALL_TEXT_LIMIT]}")
        return "\n".join(lines)

    async def open_command(argv: list[str], what: str) -> str:
        result = await runner(argv, timeout=OPEN_TIMEOUT_S, limit=OPEN_OUTPUT_LIMIT)
        if result.returncode != 0:
            raise ToolFailure(f"Could not open {what}. {result.output.strip()}".strip())
        return f"Opened {what}."

    async def open_app(args: dict[str, Any]) -> str:
        name = _text_arg(args, "name")
        if name.startswith("-"):
            raise ToolFailure("That is not an app name.")
        return await open_command(["open", "-a", name], name)

    async def open_url(args: dict[str, Any]) -> str:
        url = _text_arg(args, "url")
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ToolFailure("Only http and https links can be opened.")
        return await open_command(["open", url], url)

    async def shell(args: dict[str, Any]) -> str:
        command = _text_arg(args, "command")
        result = await runner(
            ["/bin/sh", "-c", command], timeout=shell_timeout, limit=shell_limit, cwd=Path.home()
        )
        output = result.output.rstrip() + ("\n[output truncated]" if result.truncated else "")
        if result.returncode is None:
            raise ToolFailure(
                f"The command did not finish within {shell_timeout:g} seconds and was stopped.\n{output}"
            )
        report = f"exit code {result.returncode}\n{output}".rstrip()
        if result.returncode != 0:
            raise ToolFailure(report)
        return report

    return [
        Tool(
            ToolSpec(
                "remember",
                "Save a fact to long-term memory. Call this when the user tells you something "
                "worth keeping (a date, a preference, a plan) or asks you to remember it.",
                _schema("text", "The fact to keep, written so it makes sense on its own later."),
            ),
            remember,
            "Save a note",
            "text",
        ),
        Tool(
            ToolSpec(
                "recall",
                "Search saved notes and past conversations. Call this when the user asks what "
                "you know or remember, or refers to something from an earlier conversation.",
                _schema("query", "Words to search for."),
            ),
            recall,
            "Search memory",
            "query",
        ),
        Tool(
            ToolSpec(
                "open_app",
                "Open an application on this Mac. Call this when the user asks to open or "
                "launch an app.",
                _schema("name", "The app's name, for example Safari or Calendar."),
            ),
            open_app,
            "Open an app",
            "name",
        ),
        Tool(
            ToolSpec(
                "open_url",
                "Open a web link in the default browser. Call this when the user asks to open "
                "a website or link. Only http and https links work.",
                _schema("url", "The full http or https URL."),
            ),
            open_url,
            "Open a link",
            "url",
        ),
        Tool(
            ToolSpec(
                "shell",
                "Run a shell command on this Mac and return its output. The user must approve "
                "every command first. Call this only when the user asks you to run a command "
                "or when no other tool can do what they asked.",
                _schema("command", "The command line to run with /bin/sh."),
            ),
            shell,
            "Run a shell command",
            "command",
        ),
    ]
