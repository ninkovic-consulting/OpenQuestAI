"""An agent's four procedure tools, behind the gate like every other.

`save_procedure`, `list_procedures`, `read_procedure` and `remove_procedure`
work on the procedures of the agent they were built for: its own, and the
shared ones. They are its own written notes, so their tier is free (set in
`[gate.tiers]`, not here); the store's refusals come back to the model as
failed results in plain words.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from typing import Any

from vision.core.interfaces import ToolSpec
from vision.gate.tools import Tool, ToolFailure
from vision.procedures.store import NAME_MAX, STEPS_MAX, WHEN_MAX, Procedure, ProcedureError, Procedures, Saved

NAMES = ("save_procedure", "list_procedures", "read_procedure", "remove_procedure")


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


async def _run[T](call: Any, *args: Any) -> T:
    """Run a blocking store call off the loop; its refusal becomes the tool's."""
    try:
        result: T = await asyncio.to_thread(call, *args)
    except ProcedureError as exc:
        raise ToolFailure(str(exc)) from None
    return result


def _opened(n: int) -> str:
    return "never opened" if n == 0 else "opened once" if n == 1 else f"opened {n} times"


def build_tools(store: Procedures, agent: str, names: Mapping[str, str] | None = None) -> list[Tool]:
    """The four tools for `agent`, in a fixed order (stable for prompt caching).

    `names` maps agent ids to the names people know them by, for saying who shared one.
    """
    known = dict(names or {})

    def whose(p: Procedure) -> str:
        if not p.shared:
            return "your own"
        return "shared by you" if p.author == agent else f"shared by {known.get(p.author, p.author)}"

    async def save_procedure(args: dict[str, Any]) -> str:
        shared = args.get("shared", False)
        if not isinstance(shared, bool):
            raise ToolFailure("`shared` is true or false.")
        saved: Saved = await _run(store.save, agent, args.get("name"), args.get("when"), args.get("steps"), shared)
        p = saved.procedure
        did = "Improved" if saved.replaced else "Saved"
        if p.shared:
            said = f"{did} the shared procedure “{p.title}” (`{p.name}`); every agent sees it now."
            if saved.moved:
                said += " Your own copy became the shared one."
            return said
        said = f"{did} your procedure “{p.title}” (`{p.name}`)."
        if saved.shadows:
            said += " A shared procedure has the same name; yours now takes its place for you."
        return said

    async def list_procedures(args: dict[str, Any]) -> str:
        found: list[Procedure] = await _run(store.list, agent)
        if not found:
            return "You have no procedures yet, and none are shared."
        lines = ["Your procedures, then the shared ones:"]
        for p in found:
            changed = time.strftime("%Y-%m-%d", time.localtime(p.changed_at))
            lines.append(
                f"- `{p.name}` “{p.title}” ({whose(p)}; {_opened(p.opened)}; changed {changed}): {p.when or '(no line on when)'}"
            )
        return "\n".join(lines)

    async def read_procedure(args: dict[str, Any]) -> str:
        p: Procedure = await _run(store.read, agent, args.get("name") or "")
        steps = p.steps or "(No steps written yet.)"
        if len(steps) > STEPS_MAX:
            steps = steps[:STEPS_MAX] + "\n[The rest is cut: the file is longer than a procedure may be.]"
        changed = time.strftime("%Y-%m-%d %H:%M", time.localtime(p.changed_at))
        return (
            f"“{p.title}” (`{p.name}`, {whose(p)}; {_opened(p.opened)}; changed {changed})\n"
            f"When to use: {p.when or '(not said)'}\n\nSteps:\n{steps}"
        )

    async def remove_procedure(args: dict[str, Any]) -> str:
        p: Procedure = await _run(store.remove, agent, args.get("name") or "")
        return f"Removed the shared procedure “{p.title}”." if p.shared else f"Removed your procedure “{p.title}”."

    name_arg = {"type": "string", "description": "The procedure's name (as list_procedures shows it) or its title."}
    return [
        Tool(
            ToolSpec(
                "save_procedure",
                "Save how you did a kind of work as a procedure you can follow next time, or improve one "
                "you have (saving under the same name replaces it). Use it after work that went well and "
                "is likely to come again: write steps someone could follow, with the commands, paths and "
                "checks that mattered, not a story of this job. Share it (shared=true) only when it is "
                "useful to every agent of the house; a shared one can be changed only by the agent that "
                "wrote it or the host. These are your own written notes: saving needs nobody's yes.",
                _schema(
                    {
                        "name": {"type": "string", "description": f"A short title, such as “Release the shop app” (up to {NAME_MAX} characters)."},
                        "when": {"type": "string", "description": f"One line on when to use it (up to {WHEN_MAX} characters)."},
                        "steps": {"type": "string", "description": f"The steps, numbered, in Markdown (up to {STEPS_MAX:,} characters)."},
                        "shared": {"type": "boolean", "description": "Share it with every agent. Default false: your own."},
                    },
                    ["name", "when", "steps"],
                ),
            ),
            save_procedure,
            "Save a procedure",
            "name",
            describe=lambda args: f"Save the procedure “{args.get('name', '?')}”" + (" (shared)" if args.get("shared") is True else ""),
        ),
        Tool(
            ToolSpec(
                "list_procedures",
                "List your procedures and the shared ones: name, title, when to use each, how often it was "
                "opened. Use it to find the one that covers the work in front of you.",
                _schema({}, []),
            ),
            list_procedures,
            "List its procedures",
            "",
            describe=lambda args: "Reads the list of its procedures.",
        ),
        Tool(
            ToolSpec(
                "read_procedure",
                "Open one of your procedures or a shared one and read its steps. Do this before you do a "
                "kind of work a procedure covers, then follow it; afterwards improve it with "
                "save_procedure if something was missing or wrong.",
                _schema({"name": name_arg}, ["name"]),
            ),
            read_procedure,
            "Open a procedure",
            "name",
            describe=lambda args: f"Open the procedure “{args.get('name', '?')}”",
        ),
        Tool(
            ToolSpec(
                "remove_procedure",
                "Remove one of your procedures that is wrong or no longer needed, or a shared one you "
                "wrote (the host may remove any shared one).",
                _schema({"name": name_arg}, ["name"]),
            ),
            remove_procedure,
            "Remove a procedure",
            "name",
            describe=lambda args: f"Remove the procedure “{args.get('name', '?')}”",
        ),
    ]
