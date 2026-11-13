"""The host's tools for the board: hand off work, list it, look at one job, cancel one.

Free tier and behind the gate like every other tool. They are the host's
only way to give work to a resident, and they are allowed during an
automation's run and from the phone. The resident sees nothing of the
conversation, so `hand_off` insists on a brief that stands on its own.
"""

from __future__ import annotations

from typing import Any

from vision.core.interfaces import ToolSpec
from vision.core.turns import current_origin
from vision.gate.tools import Tool, ToolFailure
from vision.jobs.board import Board, JobError, NotFound
from vision.jobs.words import details, line

HAND_OFF = (
    "Give a piece of work to one of the residents of the house, who does it in a room of the "
    "house with that room's tools while you carry on talking. Use it when the owner asks for something "
    "a resident is for: the maker for code and projects, the checker for tests and reviews, "
    "the scout for questions that need the web, the steward for this Mac and the house, the "
    "envoy for drafting messages (it cannot send any). It returns at once; you are told the "
    "result later in a turn of its own, and then you tell the owner. The resident sees nothing "
    "of this conversation: write a complete brief that stands on its own, with the goal, every "
    "fact, name, file or path it needs, and what to give back. A resident may work in any room "
    "but the Hall, with that room's project folder and tools: when the work is about a project, "
    "send the resident to the room that holds it (for example the checker to the Workshop to "
    "test the maker's project). Leave room out to use the agent's own first room. Set careful "
    "only when the owner asks for extra care, since it uses a dearer model."
)


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


def build_tools(board: Board) -> list[Tool]:
    """The four tools, in a fixed order (stable for prompt caching)."""

    def name(agent_id: str) -> str:
        return board.agent_name(agent_id)

    def find(args: dict[str, Any]) -> Any:
        ref = args.get("job")
        if not isinstance(ref, str) or not ref.strip():
            raise ToolFailure("Say which job, by its id.")
        try:
            return board.find(ref)
        except NotFound as exc:
            raise ToolFailure(f"{exc} Call list_jobs to see them.") from None

    async def hand_off(args: dict[str, Any]) -> str:
        origin = current_origin()
        try:
            job = await board.hand_off(
                str(args.get("agent", "")),
                args.get("brief", ""),
                room=args.get("room") if isinstance(args.get("room"), str) else None,
                title=args.get("title") if isinstance(args.get("title"), str) else None,
                careful=args.get("careful") is True,
                via=origin.source if origin is not None else "",
            )
        except JobError as exc:
            raise ToolFailure(str(exc)) from None
        room = board.room_name(job.room)
        where = f" in the {room}" if room else ""
        if job.status == "working":
            state = "has started"
        else:
            ahead = sum(1 for j in board.open_jobs() if j.status == "queued" and j.created_at < job.created_at)
            state = f"is waiting to start ({ahead} job{'s' if ahead != 1 else ''} ahead of it)"
        return (
            f'Handed to {name(job.agent)}{where} as job {job.id}, "{job.title}". It {state}. You '
            "will be told the result in a turn of its own; tell the owner briefly that it is in hand."
        )

    async def list_jobs(args: dict[str, Any]) -> str:
        jobs = board.all(20)
        if not jobs:
            return "There are no jobs on the board."
        open_count = sum(1 for j in jobs if j.open)
        head = f"{open_count} open, newest first (at most 20 shown):"
        return "\n".join([head, *(line(j, name) for j in jobs)])

    async def job_details(args: dict[str, Any]) -> str:
        job = find(args)
        return details(job, name, board.room_name(job.room))

    async def cancel_job(args: dict[str, Any]) -> str:
        job = find(args)
        try:
            await board.cancel(job.id)
        except JobError as exc:
            raise ToolFailure(str(exc)) from None
        return f'Cancelled job {job.id}, "{job.title}", for {name(job.agent)}.'

    def describe(args: dict[str, Any]) -> str:
        return f"{args.get('agent', '?')}: {str(args.get('brief', ''))[:200]}"

    ref = _schema({"job": {"type": "string", "description": "The job's id."}}, ["job"])
    return [
        Tool(
            ToolSpec(
                "hand_off",
                HAND_OFF,
                _schema(
                    {
                        "agent": {"type": "string", "description": "The resident's name or id, e.g. Tink or maker."},
                        "brief": {
                            "type": "string",
                            "description": "The whole task, written for someone who heard nothing of this conversation.",
                        },
                        "room": {
                            "type": "string",
                            "description": "The room to work in, by name or id: any room but the Hall. Optional.",
                        },
                        "title": {"type": "string", "description": "A few words naming the job. Optional."},
                        "careful": {"type": "boolean", "description": "Use the agent's heavy model. Optional."},
                    },
                    ["agent", "brief"],
                ),
            ),
            hand_off,
            "Hand off work",
            "brief",
            describe,
        ),
        Tool(
            ToolSpec(
                "list_jobs",
                "List the jobs on the board, newest first: who has each, whether it waits, works or "
                "ended, and how. Use it when the owner asks what the residents are doing or about "
                "work in progress.",
                _schema({}, []),
            ),
            list_jobs,
            "List jobs",
            "",
            describe=lambda args: "Reads the job board.",
        ),
        Tool(
            ToolSpec(
                "job_details",
                "One job in full: its brief, room, steps so far, result or problem, and cost. Use it "
                "when the owner asks how a particular job is going or what came of it.",
                ref,
            ),
            job_details,
            "Look at a job",
            "job",
        ),
        Tool(
            ToolSpec(
                "cancel_job",
                "Stop a job that waits or works, with any request it made to another resident. Use "
                "it only when the owner asks to stop or cancel that work.",
                ref,
            ),
            cancel_job,
            "Cancel a job",
            "job",
        ),
    ]
