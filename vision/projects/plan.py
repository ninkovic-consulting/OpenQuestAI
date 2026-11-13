"""What starting a project will do, worked out before anything is done, and the card's words.

`plan_project` reads the request, the house plan and the projects root and
decides everything: the folder (created inside the root, or an existing one
attached), whether git is initialised, the room (a new one in the free spot
nearest the Hall, or, when the house has all its extra rooms, the agent's
room that holds no project yet), its tools, and the first job. It writes
nothing. `card` puts that plan into the words the owner approves, and the
tool carries out exactly that plan.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vision.house import grid
from vision.house.folders import check_rules
from vision.house.model import HALL, HOST, Cell, HouseError, Room
from vision.house.project import check_name, rooms_named
from vision.house.tools import Catalog, load_catalog, propose_tools
from vision.jobs.model import BRIEF_MAX
from vision.projects.names import Refused, RootProblem, folder_name, projects_root

DESCRIPTION_MAX = 2000
REASON_MAX = 300
ROOM_NAME_MAX = 40
"""As long as the window lets a room's name be."""
KIND_ALIASES = {
    "node": "npm",
    "nodejs": "npm",
    "javascript": "npm",
    "typescript": "npm",
    "js": "npm",
    "ts": "npm",
    "swift": "xcode",
    "ios": "xcode",
    "macos": "xcode",
}
"""Words for a kind of project that name a catalog tool differently."""


@dataclass(frozen=True, slots=True)
class Request:
    name: str
    description: str
    agent: str
    reason: str
    kind: str | None = None
    first_job: str | None = None
    attach: str | None = None
    """An existing folder to attach instead of creating one."""


@dataclass(frozen=True, slots=True)
class Place:
    """Where the project goes in the house."""

    room_id: str | None
    """The existing room it goes into; None when a room is added."""
    room_name: str
    at: Cell | None = None
    """The new room's cell."""
    beside: tuple[str, ...] = ()
    """The rooms the new one shares a wall with."""


@dataclass(frozen=True, slots=True)
class ProjectPlan:
    name: str
    description: str
    agent: str
    agent_name: str
    reason: str
    folder: Path
    """The folder's real full path."""
    stored: str
    """The folder as the room lists it: under the root as the owner wrote it, or as attached."""
    create: bool
    git: Path | None
    """The git program, when the new folder becomes a repository."""
    tools: tuple[str, ...]
    place: Place
    first_job: str | None
    kind: str | None
    kind_matched: bool


def read_request(args: dict[str, Any]) -> Request:
    """The tool's arguments, checked. Raises `Refused`."""

    def text(key: str, limit: int, *, required: bool) -> str | None:
        value = args.get(key)
        if value is None or (isinstance(value, str) and not value.strip() and not required):
            return None
        if not isinstance(value, str) or not value.strip():
            raise Refused(f"`{key}` must be non-empty text.")
        if len(value.strip()) > limit:
            raise Refused(f"`{key}` is {len(value.strip())} characters; use at most {limit}.")
        return value.strip()

    raw_name = args.get("name")
    if not isinstance(raw_name, str):
        raise Refused("Give the project a name.")
    try:
        name = check_name(raw_name, "The project")
    except HouseError as exc:
        raise Refused(str(exc)) from None
    if name is None:
        raise Refused("Give the project a name.")
    return Request(
        name=name,
        description=text("description", DESCRIPTION_MAX, required=True) or "",
        agent=text("agent", 80, required=True) or "",
        reason=" ".join((text("reason", REASON_MAX, required=True) or "").split()),
        kind=text("kind", 40, required=False),
        first_job=text("first_job", BRIEF_MAX, required=False),
        attach=text("folder", 1024, required=False),
    )


def plan_project(
    req: Request,
    plan: dict[str, Any],
    root: str,
    *,
    git: Path | None,
    catalog: Catalog | None = None,
) -> ProjectPlan:
    """Everything starting this project would do, or `Refused` with why. Writes nothing."""
    catalog = load_catalog() if catalog is None else catalog
    agent = _agent(plan, req.agent)
    taken = rooms_named(plan["rooms"], req.name)
    if taken:
        raise Refused(
            f"The {taken[0]['name']} already holds a project called {req.name!r}. Choose another "
            "name, or hand the work to that room."
        )
    if req.attach is not None:
        folder, stored, create = _attached(req.attach), req.attach, False
        found = propose_tools(folder, catalog)
    else:
        folder, create = _new_folder(root, req.name), True
        stored = f"{root.strip().rstrip('/')}/{folder.name}"
        found = ["git"] if git is not None and "git" in catalog else []
    kind_tool = _kind_tool(req.kind, catalog)
    wanted = {*found, *([kind_tool] if kind_tool else [])}
    return ProjectPlan(
        name=req.name,
        description=req.description,
        agent=str(agent["id"]),
        agent_name=str(agent["name"]),
        reason=req.reason,
        folder=folder,
        stored=stored,
        create=create,
        git=git if create else None,
        tools=tuple(t for t in catalog if t in wanted),
        place=_place(plan, agent, req.name),
        first_job=req.first_job,
        kind=req.kind,
        kind_matched=kind_tool is not None,
    )


def card(p: ProjectPlan, catalog: Catalog | None = None) -> str:
    """Exactly what a yes will do, in lines the owner reads on the gate card."""
    catalog = load_catalog() if catalog is None else catalog
    lines = [
        f"Project: {p.name}",
        f"Description: {p.description}",
        f"Agent: {p.agent_name} ({p.agent}). Why: {p.reason}",
    ]
    if p.create:
        lines.append(f"Folder to create: {p.folder}")
        inside = "README.md with the name and description"
        if p.git is not None:
            lines.append(f"Inside it: {inside}, and git init (git is installed).")
        else:
            lines.append(f"Inside it: {inside}. No git init: git is not installed on this Mac.")
    else:
        lines.append(f"Folder: {p.folder}, which exists; nothing in it is created or changed.")
    place = p.place
    if place.room_id is None:
        assert place.at is not None
        beside = f" next to the {_and(place.beside)}" if place.beside else ""
        lines.append(
            f'Room to add: "{place.room_name}", run by {p.agent_name}, at [{place.at[0]}, {place.at[1]}]{beside}.'
        )
    else:
        lines.append(
            f"Room: none can be added (the house has all its extra rooms), so the project goes into "
            f"the {place.room_name}, {p.agent_name}'s room with no project yet, which takes its name, "
            "folder and tools."
        )
    names = [catalog[t].title for t in p.tools]
    lines.append(f"Room tools: {', '.join(names) if names else 'none'}.")
    if p.kind and not p.kind_matched:
        lines.append(f"Kind: {p.kind}, which matches none of the house's tools.")
    if p.first_job:
        lines.append(f"First job for {p.agent_name}, in that room:")
        lines.append(p.first_job)
    else:
        lines.append("First job: none; nothing starts until it is asked for.")
    return "\n".join(lines)


def _and(names: tuple[str, ...]) -> str:
    return names[0] if len(names) == 1 else f"{', the '.join(names[:-1])} and the {names[-1]}"


def _agent(plan: dict[str, Any], ref: str) -> dict[str, Any]:
    wanted = ref.strip().casefold()
    agents = plan["agents"]
    residents = ", ".join(f"{a['name']} ({a['id']})" for a in agents if a["id"] != HOST)
    found = next((a for a in agents if wanted in (a["id"].casefold(), a["name"].casefold())), None)
    if found is None:
        raise Refused(f"There is no agent called {ref!r}. Give the project to one of: {residents}.")
    if found["id"] == HOST:
        raise Refused(
            f"{found['name']} is the host: it hands out projects and runs no room of its own. "
            f"Give the project to one of: {residents}."
        )
    return found


def _attached(given: str) -> Path:
    if not given.startswith(("/", "~")):
        raise Refused(f"The folder {given} must be a full path, starting with / or ~.")
    real = Path(os.path.realpath(Path(given).expanduser()))
    if not real.is_dir():
        raise Refused(f"{given} is not a folder on this Mac, so it cannot be attached.")
    try:
        check_rules((given,), "The project")
    except HouseError as exc:
        raise Refused(str(exc)) from None
    return real


def _new_folder(root: str, name: str) -> Path:
    try:
        base = projects_root(root)
    except RootProblem as exc:
        raise Refused(
            f"The folder for new projects cannot be used: {exc} So no project folder can be created. "
            "The owner can create it, or choose another in Settings, Rooms, Where new projects go; or "
            "an existing folder can be attached with `folder`."
        ) from None
    target = base / folder_name(name)
    if os.path.lexists(target):
        raise Refused(
            f"{base} already has something called {target.name}, and a project never goes over "
            "what exists. Choose another name, or attach that folder with `folder`."
        )
    return target


def _kind_tool(kind: str | None, catalog: Catalog) -> str | None:
    if not kind:
        return None
    word = kind.strip().casefold()
    tool = KIND_ALIASES.get(word, word)
    info = catalog.get(tool)
    return tool if info is not None and not info.built_in else None


def _place(plan: dict[str, Any], agent: dict[str, Any], project: str) -> Place:
    rooms = plan["rooms"]
    extras = sum(1 for r in rooms if r["kind"] == "extra")
    if extras < plan["max_extra_rooms"]:
        laid = [_room(r) for r in rooms]
        occ = grid.occupancy(laid)
        hall = next(r for r in laid if r.id == HALL)
        at = grid.nearest_spot(occ, (1, 1), hall)
        beside = tuple(
            dict.fromkeys(
                next(r.name for r in laid if r.id == occ[cell])
                for side in grid.SIDES
                if (cell := grid.step(at, side)) in occ
            )
        )
        return Place(None, _room_name(project), at, beside)
    free = next(
        (r for r in rooms if r["agent"] == agent["id"] and not r.get("project") and not r["folders"]),
        None,
    )
    if free is None:
        raise Refused(
            f"The house already has all {plan['max_extra_rooms']} extra rooms, and none of "
            f"{agent['name']}'s rooms is free of a project, so the project has nowhere to go. The owner "
            f"can remove an extra room (Settings, Rooms), clear the project name and folders of one of "
            f"{agent['name']}'s rooms, or give the project to another agent."
        )
    return Place(str(free["id"]), str(free["name"]))


def _room(r: dict[str, Any]) -> Room:
    """A plan room as the grid reads it."""
    return Room(
        id=r["id"],
        name=r["name"],
        kind=r["kind"],
        shape=r["shape"],
        at=(r["at"][0], r["at"][1]),
        size=(r["size"][0], r["size"][1]),
        agent=r["agent"],
        model=None,
        folders=(),
        floor=r["floor"],
        wall=r["wall"],
    )


def _room_name(project: str) -> str:
    """The project's name, cut at a word to fit a room's name."""
    if len(project) <= ROOM_NAME_MAX:
        return project
    cut = project[: ROOM_NAME_MAX + 1].rsplit(" ", 1)[0].rstrip(" -,.")
    return cut if 0 < len(cut) <= ROOM_NAME_MAX else project[:ROOM_NAME_MAX].rstrip()
