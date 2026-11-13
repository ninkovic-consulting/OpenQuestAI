"""`start_project`: the host's tool for a new project, with its own room and resident.

It always asks first (`vision.gate.policy.NEVER_FREE`), and residents never
get it (`vision.residents.abilities.HOST_ONLY`). The card is the plan in
words (`plan.card`), worked out from the house and the folders when the gate
asks; the call carries out that plan, and refuses when what it would do now
differs from what the owner approved.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from vision.core.interfaces import ToolSpec
from vision.core.programs import find_program
from vision.core.turns import current_origin
from vision.gate.tools import Runner, Tool, ToolFailure, run_command
from vision.jobs.board import Board
from vision.projects.make import ProjectHouse, carry_out
from vision.projects.names import Refused
from vision.projects.plan import ProjectPlan, card, plan_project, read_request

SHOWN_KEEP = 16
"""Cards remembered until their call comes (a few may wait at once)."""

START_PROJECT = (
    "Start a new project for the owner and give it to the resident best suited to it: creates the "
    "project's folder in the owner's folder for new projects, with a README.md holding the name and "
    "description and a git repository, adds a room to the house holding that folder and run by that "
    "resident, and, when given, hands that resident a first job in the new room. Use it when the owner "
    "asks you to start, set up or create a new project; for work on an existing project use hand_off. "
    "The owner sees exactly what will happen and says yes first. Choose the agent from the roster: the "
    "maker for building software (apps, tools, scripts, websites), the scout for research and anything "
    "that needs the web, the envoy for writing and communication (letters, posts, messages), the steward "
    "for operations and upkeep of this Mac and the house. The checker reviews and tests others' work "
    "rather than owning a project. When the owner names an agent, give it to that one. Say in `reason`, "
    "in one sentence, why that agent. Give `first_job` only when the owner wants work to start now, as a "
    "complete brief like hand_off's: the resident sees nothing of this conversation. Set `folder` only to "
    "attach an existing folder instead of creating one. You will be told the first job's result later, "
    "in a turn of its own."
)


def _schema() -> dict[str, Any]:
    def text(description: str) -> dict[str, str]:
        return {"type": "string", "description": description}

    return {
        "type": "object",
        "properties": {
            "name": text("The project's name, as the owner would say it, up to 60 characters; the folder name is made from it."),
            "description": text("What the project is, in the owner's words; it goes into the README."),
            "agent": text("The resident to give it to, by name or id, e.g. Tink or maker. Never the host."),
            "reason": text("One sentence on why that agent suits this project."),
            "kind": text("Optional: the kind of project, a hint for the room's tools, e.g. python, node, xcode, docker."),
            "first_job": text("Optional: a first job for that agent in the new room, as a complete brief."),
            "folder": text("Optional: an existing folder to attach instead of creating one, a full path."),
        },
        "required": ["name", "description", "agent", "reason"],
        "additionalProperties": False,
    }


def build_tools(
    house: Callable[[], object],
    board: Board,
    root: Callable[[], str],
    *,
    finder: Callable[[str], Path | None] = find_program,
    runner: Runner = run_command,
) -> list[Tool]:
    """The one tool. `house` and `root` are read at each call: the house the daemon runs now,
    and `[projects] root` as config.toml holds it now."""
    shown: dict[str, str] = {}

    def editable() -> ProjectHouse | None:
        home = house()
        return home if isinstance(home, ProjectHouse) else None

    def plan(args: dict[str, Any]) -> ProjectPlan:
        home = editable()
        if home is None:
            raise Refused("This house cannot be changed, so no project can be started here.")
        return plan_project(read_request(args), home.plan(), root(), git=finder("git"))

    def describe(args: dict[str, Any]) -> str:
        try:
            text = card(plan(args))
        except Refused as exc:
            return f"This cannot be done, so a yes changes nothing: {exc}"
        shown[_key(args)] = text
        while len(shown) > SHOWN_KEEP:
            shown.pop(next(iter(shown)))
        return text

    async def start_project(args: dict[str, Any]) -> str:
        try:
            p = plan(args)
        except Refused as exc:
            raise ToolFailure(f"{exc} Nothing was created.") from None
        approved = shown.pop(_key(args), None)
        if approved is not None and approved != card(p):
            raise ToolFailure(
                "The house or the folders changed after the owner was asked, so nothing was done. Ask "
                "again to show what would happen now."
            )
        home = editable()
        assert home is not None
        origin = current_origin()
        return await carry_out(p, home, board, runner=runner, via=origin.source if origin is not None else "")

    return [
        Tool(
            ToolSpec("start_project", START_PROJECT, _schema()),
            start_project,
            "Start a new project",
            "name",
            describe,
        )
    ]


def _key(args: dict[str, Any]) -> str:
    return json.dumps(args, sort_keys=True, ensure_ascii=False)
