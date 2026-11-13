"""A resident's own tools at work: its notes, progress lines, and asking another resident.

- `remember`, `recall`: the resident's own notes (`ResidentNotes`), never the
  host's or another resident's.
- `note_progress(text)`: a step on the job's record, shown live.
- `ask_resident(agent, brief)`: a request on the board for another resident,
  run as a child job; the call returns that job's result. Not offered in a
  request from another resident (depth 1); the board also refuses the host,
  the resident itself, a busy resident and a fourth request.
- `machine_status`: the steward's look at this Mac (`machine.py`).

Each is a gate tool with its own tier, like every other.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from vision.core.interfaces import ToolSpec
from vision.gate.tools import Tool, ToolFailure
from vision.jobs import Desk, JobError
from vision.jobs.model import clip
from vision.residents.machine import Probe, describe
from vision.residents.notes import ResidentNotes

RECALL_LIMIT = 5
RECALL_TEXT = 500
PROGRESS_MAX = 200
ASK_RESULT_MAX = 6000


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


def _text(args: dict[str, Any], name: str) -> str:
    value = args.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ToolFailure(f"`{name}` must be a non-empty string.")
    return value.strip()


def own_tools(notes: ResidentNotes, desk: Desk, *, may_ask: bool) -> list[Tool]:
    """remember, recall, note_progress and (unless this is a request) ask_resident."""

    async def remember(args: dict[str, Any]) -> str:
        await asyncio.to_thread(notes.remember, _text(args, "text"))
        return "Noted in your own notes."

    async def recall(args: dict[str, Any]) -> str:
        found = await asyncio.to_thread(notes.recall, _text(args, "query"), RECALL_LIMIT)
        if not found:
            return "Nothing in your notes about that."
        return "\n".join(
            f"- [{time.strftime('%Y-%m-%d', time.localtime(n.ts))}] {n.text[:RECALL_TEXT]}" for n in found
        )

    async def note_progress(args: dict[str, Any]) -> str:
        desk.step("progress", clip(_text(args, "text"), PROGRESS_MAX))
        return "Shown."

    async def ask_resident(args: dict[str, Any]) -> str:
        room = args.get("room")
        try:
            child = await desk.ask(
                _text(args, "agent"), _text(args, "brief"), room if isinstance(room, str) and room.strip() else None
            )
        except JobError as exc:
            raise ToolFailure(str(exc)) from None
        who = desk.board.agent_name(child.agent)
        if child.status == "done":
            return f"{who} answered (job {child.id}):\n{clip(child.result, ASK_RESULT_MAX) or '(no text)'}"
        said = f"\nWhat they had so far:\n{clip(child.result, ASK_RESULT_MAX)}" if child.result else ""
        raise ToolFailure(f"{who}'s job {child.id} {child.status}: {child.error or 'no reason given'}{said}")

    tools = [
        Tool(
            ToolSpec(
                "remember",
                "Save a note to your own notes, for your future jobs: something about your projects "
                "or how the owner likes things done that is worth knowing next time.",
                _schema({"text": {"type": "string", "description": "The note, written to make sense on its own later."}}, ["text"]),
            ),
            remember,
            "Save a note",
            "text",
        ),
        Tool(
            ToolSpec(
                "recall",
                "Search your own notes from earlier jobs.",
                _schema({"query": {"type": "string", "description": "Words to search for."}}, ["query"]),
            ),
            recall,
            "Search its notes",
            "query",
        ),
        Tool(
            ToolSpec(
                "note_progress",
                "Show a short line on the job's record, for the owner to follow along: a milestone "
                "reached or what you are about to do next in longer work. Not for the final result.",
                _schema({"text": {"type": "string", "description": f"One short line, at most {PROGRESS_MAX} characters."}}, ["text"]),
            ),
            note_progress,
            "Note progress",
            "text",
        ),
    ]
    if may_ask:
        tools.append(
            Tool(
                ToolSpec(
                    "ask_resident",
                    "Ask another resident of the house (not the host, not yourself) to do part of this "
                    "job, through the job board, and wait for their result. Use it only when the part "
                    "is clearly theirs (for example the checker for tests, the scout for the web). They "
                    "work in this job's room, on the same project folders, unless you name another "
                    "room; name the room whose project the part is about. They see nothing of your "
                    "job: write a complete brief. At most three requests per job; a busy resident is "
                    "refused.",
                    _schema(
                        {
                            "agent": {"type": "string", "description": "The resident's name or id."},
                            "brief": {"type": "string", "description": "The whole request, standing on its own."},
                            "room": {
                                "type": "string",
                                "description": "The room to work in, by name or id. Optional; this job's room when left out.",
                            },
                        },
                        ["agent", "brief"],
                    ),
                ),
                ask_resident,
                "Ask another resident",
                "brief",
                lambda args: f"{args.get('agent', '?')}: {str(args.get('brief', ''))[:200]}",
            )
        )
    return tools


def machine_tool(probe: Probe) -> Tool:
    async def run(args: dict[str, Any]) -> str:
        return describe(await probe.read())

    return Tool(
        ToolSpec(
            "machine_status",
            "Read this Mac's state: free disk space, memory, battery, how long it has been up, and "
            "the load. Read-only.",
            _schema({}, []),
        ),
        run,
        "Check the Mac",
        "",
        describe=lambda args: "Reads disk, memory, battery, uptime and load.",
    )
