"""Carrying out an approved plan: the folder, its README, git, the room, the first job.

Each step runs only when the one before it worked, except `git init`, whose
failure is told while the rest goes on: a project without a repository is
still a project. A new folder is made with `mkdir`, never over anything that
exists, and its README with exclusive creation. Nothing is ever deleted: when
a step fails after the folder exists, the failure says what exists now and
what does not, so the owner (or the host, asked again with `folder`) can
carry on from there.
"""

from __future__ import annotations

import os
from typing import Any, Protocol, runtime_checkable

from vision.gate.tools import Runner, ToolFailure
from vision.house.model import HouseError
from vision.house.tools import load_catalog
from vision.jobs.board import Board, JobError
from vision.projects.plan import ProjectPlan
from vision.workbench.programs import clean_environment

GIT_TIMEOUT_S = 30.0
GIT_OUTPUT_LIMIT = 2000


@runtime_checkable
class ProjectHouse(Protocol):
    """What starting a project needs of the house (`vision.house.GridHouse` has it)."""

    def plan(self) -> dict[str, Any]: ...
    async def add_room(self, fields: dict[str, Any]) -> dict[str, Any]: ...
    async def update_room(self, room_id: str, fields: dict[str, Any]) -> dict[str, Any]: ...


def readme(p: ProjectPlan) -> str:
    return f"# {p.name}\n\n{p.description}\n"


async def carry_out(p: ProjectPlan, house: ProjectHouse, board: Board, *, runner: Runner, via: str) -> str:
    """Do what the card said. Returns words for the model; raises `ToolFailure` saying what exists."""
    done: list[str] = []
    later: list[str] = []
    if p.create:
        _make_folder(p)
        done.append(f"created the folder {p.folder} with its README.md")
    if p.git is not None:
        failed = await _git(p, runner)
        if failed:
            later.append(failed)
        else:
            done.append("made it a git repository")
    room_id, room_words = await _room(p, house, done)
    if not p.create:
        done.append(f"attached the folder {p.folder}, changing nothing in it")
    done.append(room_words)
    if p.first_job:
        try:
            job = await board.hand_off(p.agent, p.first_job, room=room_id, via=via)
        except JobError as exc:
            raise _stopped(done, f"the first job could not be handed off ({exc})", "the first job") from None
        state = "it has started" if job.status == "working" else "it waits for a free place"
        later.append(
            f'{p.agent_name} has the first job in that room, job {job.id}, "{job.title}"; {state}. You will '
            "be told its result in a turn of its own"
        )
    told = [f'Started the project "{p.name}" for {p.agent_name}: {"; ".join(done)}', *later]
    return " ".join(f"{s}." for s in told)


def _make_folder(p: ProjectPlan) -> None:
    try:
        os.mkdir(p.folder, 0o755)
    except FileExistsError:
        raise ToolFailure(
            f"Something called {p.folder.name} appeared in {p.folder.parent} before the folder could be "
            "created, so nothing was done."
        ) from None
    except OSError as exc:
        raise ToolFailure(f"The folder {p.folder} could not be created ({exc.strerror}), so nothing was done.") from None
    try:
        with open(p.folder / "README.md", "x", encoding="utf-8") as fh:
            fh.write(readme(p))
    except OSError as exc:
        raise _stopped(
            [f"the folder {p.folder}, empty"],
            f"README.md could not be written ({exc.strerror})",
            "README.md, git, the room and the first job",
        ) from None


async def _git(p: ProjectPlan, runner: Runner) -> str | None:
    """`git init` in the new folder with the project tools' clean environment; None when it worked."""
    assert p.git is not None
    try:
        result = await runner(
            [str(p.git), "init", "-q"],
            timeout=GIT_TIMEOUT_S,
            limit=GIT_OUTPUT_LIMIT,
            cwd=p.folder,
            env=clean_environment({"git": p.git}),
        )
    except OSError as exc:
        return f"git init could not run ({exc.strerror}), so the folder is not a git repository"
    if result.returncode == 0:
        return None
    why = "it did not finish in time" if result.returncode is None else " ".join(result.output.split())[:300]
    return f"git init did not work ({why}), so the folder is not a git repository"


async def _room(p: ProjectPlan, house: ProjectHouse, done: list[str]) -> tuple[str, str]:
    """Add the room, or give the project to the agent's free room. Returns its id and words."""
    tools = ", ".join(load_catalog()[t].title for t in p.tools) or "none"
    place = p.place
    try:
        if place.room_id is None:
            assert place.at is not None
            room = await house.add_room(
                {
                    "name": place.room_name,
                    "agent": p.agent,
                    "folders": [p.stored],
                    "project": p.name,
                    "tools": list(p.tools),
                    "at": list(place.at),
                }
            )
            return str(room["id"]), f'added the room "{room["name"]}" (tools: {tools})'
        room = await house.update_room(place.room_id, {"project": p.name, "folders": [p.stored], "tools": list(p.tools)})
        return str(room["id"]), (
            f"gave it to the {room['name']}, {p.agent_name}'s room with no project, since the house has all "
            f"its extra rooms (tools: {tools})"
        )
    except HouseError as exc:
        raise _stopped(done, f"the room could not be set up ({exc})", "a room holding the project, and the first job") from None


def _stopped(done: list[str], what: str, missing: str) -> ToolFailure:
    """A failure after something was made: what exists, what does not, and that nothing was deleted."""
    exists = f"What exists now: {'; '.join(done)}." if done else "Nothing new was made."
    return ToolFailure(
        f"Starting the project stopped partway: {what}. {exists} What does not: {missing}. Nothing was "
        "deleted. To carry on, ask again with `folder` set to the project's folder, or add it to a room in "
        "Settings, Rooms."
    )
