"""The agents' side: propose_tool, propose_change, my_proposals, and each approved tool.

The three proposal tools only ever create a proposal or read the agent's own;
none of them can approve, decline or change anything. Their descriptions teach
the model what a made tool gets and how it is confined, and that a refusal is
not a puzzle to solve: an agent never proposes a tool to get around something
it was refused.

An approved, enabled tool appears to the agents it was approved for as
`made_<name>`, a gate tool like any other, with the tier the owner chose and
an audit stamp naming the exact version and hash that ran.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from vision.core.interfaces import ToolSpec
from vision.gate.tools import Tool, ToolFailure
from vision.proposals.changes import WORDS
from vision.proposals.made import RUN_TIMEOUT_S, MadeTool
from vision.proposals.model import (
    DESCRIPTION_MAX,
    PERSONA_MAX,
    REASON_MAX,
    SCRIPT_MAX,
    Context,
    Proposal,
    ProposalError,
)

if TYPE_CHECKING:
    from vision.proposals.service import Proposals

MINE_LIMIT = 20
CARD_INPUT = 1_500

PROPOSE_TOOL = (
    "Propose a new tool for yourself: a small script that the owner reads and approves or declines at "
    "the Mac. A proposal runs nothing; it waits for the owner, and nothing about it can be approved "
    "from here, by the phone or by a typed or spoken yes. Once approved it appears as made_<name>.\n"
    "What the script gets when it runs: its input as JSON on stdin; in the environment variable "
    "FOLDERS a JSON object of short folder name -> absolute path for the folders it may read; its own "
    "empty scratch folder as the working directory, also HOME and TMPDIR; what it prints to stdout is "
    "the result. Python uses the standard library only (it runs as python3 -I -S, no packages), or "
    "write a POSIX sh script. It can read only the folders it declares (short names of the folders of "
    "the room you work in, and only when it runs in that room) and write only its scratch folder, "
    "which is deleted after each run. It has no network unless you declare it and the owner approves "
    "it. macOS confines it; it stops after 30 seconds.\n"
    "Give the reason honestly: what it is for and why your existing tools do not do it. Never propose "
    "a tool to get around something that was refused or that needs the owner's yes: carry on without "
    "it, or say what blocked you. Proposing again under an existing name of yours makes a new version, "
    "which turns the tool off until the owner decides."
)
PROPOSE_CHANGE = (
    "Propose a change to yourself: your persona (the text that describes who you are and how you "
    "work), your model, or your effort (thinking level: low, medium, high, xhigh or max). The owner "
    "sees before and after and approves or declines at the Mac; nothing changes until then. Only these "
    "three can be proposed: the approval rules, permissions, spending caps, keys, the phone's approval "
    "list and the app's own code are the owner's alone, and a proposal for them is refused. Give the "
    "reason honestly."
)
MY_PROPOSALS = "List your own proposals and what became of them: waiting, approved or declined, with the owner's note."


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


def answer(proposal: Proposal) -> str:
    """What the model hears after proposing."""
    then = "Nothing runs until then." if proposal.kind == "tool" else "Nothing changes until then."
    return (
        f"Proposal {proposal.id} is waiting for the owner, who decides at the Mac. {then} Carry on without it."
    )


def line(p: Proposal) -> str:
    """One proposal as the model sees it in my_proposals."""
    if p.status == "waiting":
        state = "waiting for the owner"
    elif p.status == "declined":
        state = "declined" + (f": {p.note}" if p.note else "")
    elif p.decision is not None:
        who = "you" if p.decision.who == "author" else "every agent"
        asks = "asks the owner each run" if p.decision.tier == "ask" else "runs freely"
        state = f"approved, for {who}; it {asks}"
    else:
        state = "approved" + (", later put back as it was" if p.restored_at is not None else "")
    return f"- {p.id}, {p.title}: {state}."


def agent_tools(proposals: Proposals, ctx: Context) -> list[Tool]:
    """propose_tool, propose_change and my_proposals for the agent in `ctx`."""

    async def propose_tool(args: dict[str, Any]) -> str:
        try:
            return answer(await proposals.propose_tool(ctx, args))
        except ProposalError as exc:
            raise ToolFailure(str(exc)) from None

    async def propose_change(args: dict[str, Any]) -> str:
        agent = args.get("agent")
        try:
            made = await proposals.propose_change(
                ctx,
                args.get("field"),
                args.get("value"),
                args.get("reason"),
                agent=agent if isinstance(agent, str) and agent.strip() else None,
            )
        except ProposalError as exc:
            raise ToolFailure(str(exc)) from None
        return answer(made)

    async def my_proposals(args: dict[str, Any]) -> str:
        mine = proposals.mine(ctx.agent)[:MINE_LIMIT]
        if not mine:
            return "You have made no proposals."
        return "\n".join(line(p) for p in mine)

    change_props: dict[str, Any] = {
        "field": {"type": "string", "enum": ["persona", "model", "effort"], "description": "What to change."},
        "value": {
            "type": "string",
            "description": f"The new value: the whole new persona text (at most {PERSONA_MAX:,} characters), "
            "a model name, or a thinking level.",
        },
        "reason": {"type": "string", "description": f"Why, for the owner (at most {REASON_MAX:,} characters)."},
    }
    if ctx.agent == "host":
        change_props["agent"] = {
            "type": "string",
            "description": "The resident to change, by name or id. Optional; yourself when left out.",
        }
    return [
        Tool(
            ToolSpec(
                "propose_tool",
                PROPOSE_TOOL,
                _schema(
                    {
                        "name": {"type": "string", "description": "3 to 40 lowercase letters, digits or _, like count_lines."},
                        "description": {
                            "type": "string",
                            "description": f"What the tool does, for whoever calls it (at most {DESCRIPTION_MAX} characters).",
                        },
                        "input_schema": {
                            "type": "object",
                            "description": 'A JSON schema of its input, with "type": "object".',
                        },
                        "language": {"type": "string", "enum": ["python", "sh"]},
                        "script": {"type": "string", "description": f"The whole script, at most {SCRIPT_MAX:,} characters."},
                        "folders": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Short names of this room's folders it needs to read. Optional.",
                        },
                        "network": {"type": "boolean", "description": "Whether it needs the network. Optional; no."},
                        "reason": {
                            "type": "string",
                            "description": f"Why you need it, for the owner (at most {REASON_MAX:,} characters).",
                        },
                    },
                    ["name", "description", "input_schema", "language", "script", "reason"],
                ),
            ),
            propose_tool,
            "Propose a new tool",
            "name",
            lambda args: f"{args.get('name', '?')}: {str(args.get('reason', ''))[:300]}",
        ),
        Tool(
            ToolSpec("propose_change", PROPOSE_CHANGE, _schema(change_props, ["field", "value", "reason"])),
            propose_change,
            "Propose a change to itself",
            "field",
            lambda args: f"{WORDS.get(str(args.get('field')), '?')}: {str(args.get('reason', ''))[:300]}",
        ),
        Tool(ToolSpec("my_proposals", MY_PROPOSALS, _schema({}, [])), my_proposals, "List its proposals", ""),
    ]


def made_tool(
    tool: MadeTool,
    reach: list[tuple[str, Path]],
    run: Callable[[dict[str, Any]], Awaitable[str]],
) -> Tool:
    """The gate tool for an approved version. `reach` is what it may read in this job."""
    now = tool.current
    network = "yes" if now.reach.network else "no"
    reads = "; ".join(f"{name} ({path})" for name, path in reach) or "nothing outside its scratch folder"
    footer = (
        f"\nMay read: {reads}\nNetwork: {network}\n"
        f"Version {now.version}, sha256 {now.sha256[:12]}, written by {tool.author_name}"
    )

    def describe(args: dict[str, Any]) -> str:
        shown = json.dumps(args, ensure_ascii=False, sort_keys=True)
        if len(shown) > CARD_INPUT:
            shown = shown[: CARD_INPUT - 1] + "…"
        return f"Input: {shown}{footer}"

    note = (
        f"\n\nA tool {tool.author_name} wrote, approved by the owner; it runs confined by macOS and stops "
        f"after {RUN_TIMEOUT_S:g} seconds."
    )
    return Tool(
        ToolSpec(tool.tool_name, now.description + note, now.input_schema),
        run,
        f"Run the new tool {tool.name}",
        "",
        describe=describe,
        tier=tool.tier,
        stamp=lambda: {"sha256": now.sha256, "version": str(now.version)},
    )
