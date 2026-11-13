"""The six workbench tools, built for one project folder.

Tiers are the caller's: list_files, read_file and search_files free;
write_file and edit_file ask; run_program always asks.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from vision.core.interfaces import ToolSpec
from vision.gate.tools import Runner, Tool, run_command
from vision.workbench import files
from vision.workbench.paths import ProjectRoot
from vision.workbench.programs import DEFAULT_TIMEOUT_S, MAX_TIMEOUT_S, ProgramRunner
from vision.workbench.search import search_files

NAMES = ("list_files", "read_file", "search_files", "write_file", "edit_file", "run_program")

_PATH = "A path relative to the project folder, for example `src/app.py`; `.` is the folder itself."


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


def project_tools(root: Path, programs: Mapping[str, Path], *, runner: Runner = run_command) -> list[Tool]:
    """The workbench tools for `root`, in a fixed order (stable for prompt caching).

    `programs` maps a tool id (such as `git`) to the absolute path of that
    program; these are the only programs run_program can start. Raises
    ValueError when `root` is not a usable project folder or `programs` is
    malformed.
    """
    project = ProjectRoot(root)
    program_runner = ProgramRunner(project, programs, runner)
    program_ids = sorted(program_runner.programs)

    async def list_tool(args: dict[str, Any]) -> str:
        return await asyncio.to_thread(files.list_files, project, args.get("path", "."), args.get("depth"))

    async def read_tool(args: dict[str, Any]) -> str:
        return await asyncio.to_thread(
            files.read_file, project, args.get("path"), args.get("start_line"), args.get("end_line")
        )

    async def search_tool(args: dict[str, Any]) -> str:
        return await search_files(project, args, runner=runner)

    async def write_tool(args: dict[str, Any]) -> str:
        return await asyncio.to_thread(files.write_file, project, args.get("path"), args.get("content"))

    async def edit_tool(args: dict[str, Any]) -> str:
        return await asyncio.to_thread(files.edit_file, project, args)

    def safe(describe: Any) -> Any:
        def wrapped(args: dict[str, Any]) -> str:
            try:
                return describe(args)
            except Exception as exc:  # the card must never break the gate
                return f"This request will be refused ({type(exc).__name__})."

        return wrapped

    return [
        Tool(
            ToolSpec(
                "list_files",
                "List the folders and files of the project you work in, with sizes. Dependencies, "
                "virtual environments, build output and caches are shown but not expanded; protected "
                "files (secrets, keys) are marked and can never be read.",
                _schema(
                    {
                        "path": {"type": "string", "description": _PATH},
                        "depth": {"type": "integer", "description": f"How many folder levels to show, 1 to {files.MAX_LIST_DEPTH} (default {files.DEFAULT_LIST_DEPTH})."},
                    },
                    [],
                ),
            ),
            list_tool,
            "List project files",
            "path",
        ),
        Tool(
            ToolSpec(
                "read_file",
                "Read a text file of the project, with line numbers. Long files come in parts: the "
                f"first {files.DEFAULT_READ_LINES} lines by default; ask for more with start_line and end_line.",
                _schema(
                    {
                        "path": {"type": "string", "description": _PATH},
                        "start_line": {"type": "integer", "description": "First line to read, from 1."},
                        "end_line": {"type": "integer", "description": "Last line to read, inclusive."},
                    },
                    ["path"],
                ),
            ),
            read_tool,
            "Read a project file",
            "path",
        ),
        Tool(
            ToolSpec(
                "search_files",
                "Search the project's text files for a Python regular expression and list the matching "
                "lines as path:line: text. Narrow it with path (a folder or file) and glob (such as `*.py`).",
                _schema(
                    {
                        "pattern": {"type": "string", "description": "A Python regular expression."},
                        "path": {"type": "string", "description": _PATH + " Default `.`."},
                        "glob": {"type": "string", "description": "Only files whose name matches, such as `*.ts`; with a `/` it matches the whole path."},
                        "ignore_case": {"type": "boolean", "description": "Match regardless of case."},
                    },
                    ["pattern"],
                ),
            ),
            search_tool,
            "Search project files",
            "pattern",
        ),
        Tool(
            ToolSpec(
                "write_file",
                "Create a file in the project, or replace one with new content in full. Folders on the "
                "way are created. The owner approves every write. For small changes to an existing file "
                "use edit_file.",
                _schema(
                    {
                        "path": {"type": "string", "description": _PATH},
                        "content": {"type": "string", "description": "The complete new content of the file."},
                    },
                    ["path", "content"],
                ),
            ),
            write_tool,
            "Write a file in the project",
            "path",
            describe=safe(lambda args: files.describe_write(project, args)),
        ),
        Tool(
            ToolSpec(
                "edit_file",
                "Change a file of the project by replacing one exact piece of text. `old` must appear "
                "exactly once in the file (include surrounding lines to make it unique). The owner "
                "approves every edit.",
                _schema(
                    {
                        "path": {"type": "string", "description": _PATH},
                        "old": {"type": "string", "description": "The exact text to replace, as it is in the file."},
                        "new": {"type": "string", "description": "The text to put in its place (may be empty)."},
                    },
                    ["path", "old", "new"],
                ),
            ),
            edit_tool,
            "Edit a file in the project",
            "path",
            describe=safe(lambda args: files.describe_edit(project, args)),
        ),
        Tool(
            ToolSpec(
                "run_program",
                "Run one of the allowed programs in the project folder, with arguments, and return its "
                "exit code and output. Not a shell: no pipes, redirection or variables; each argument "
                f"is one list item. Allowed programs: {', '.join(program_ids) or 'none'}. The owner "
                "approves every run.",
                _schema(
                    {
                        "program": {"type": "string", "enum": program_ids, "description": "The program's id."} if program_ids else {"type": "string", "description": "The program's id."},
                        "args": {"type": "array", "items": {"type": "string"}, "description": "The arguments, one per item."},
                        "timeout_s": {"type": "number", "description": f"Seconds before it is stopped (default {DEFAULT_TIMEOUT_S:g}, at most {MAX_TIMEOUT_S:g})."},
                    },
                    ["program", "args"],
                ),
            ),
            program_runner.run,
            "Run a program in the project",
            "program",
            describe=safe(program_runner.describe),
        ),
    ]
