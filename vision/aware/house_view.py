"""The house in words, for the model: a few lines of context, the overview, one room.

Everything is read from the house plan (`House.plan()`, the same one the
window draws), the agents' personas in the vault, the library, and the job
board (what each resident is doing now). What works today comes from `limits`.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from vision.aware import limits
from vision.aware.personas import Personas
from vision.jobs.model import Job
from vision.memory.library import LibraryEntry

HALL = "hall"
LIBRARY_ROOM = "library"
"""The room that holds the shared library."""
_FILLER = re.compile(r"\b(the|room|rooms)\b")


class NoSuchRoom(LookupError):
    """No room answers to that name; the message lists the rooms there are."""


@dataclass(frozen=True, slots=True)
class HouseView:
    plan: dict[str, Any]
    personas: Personas
    host_state: str
    """The assistant's own state now: idle, thinking, speaking and so on."""
    jobs: Sequence[Job] = ()
    """Jobs waiting or at work, oldest first."""
    waiting: frozenset[str] = frozenset()
    """Residents whose job waits for the owner's yes."""
    project_tools: bool = False
    """Whether the workbench's project tools are installed."""

    @property
    def name(self) -> str:
        return str(self.plan["assistant"]["name"])

    @property
    def host_id(self) -> str:
        hall = next((r for r in self.plan["rooms"] if r["id"] == HALL), None)
        return str(hall["agent"]) if hall else "host"

    def agent(self, agent_id: str) -> dict[str, Any]:
        return next(a for a in self.plan["agents"] if a["id"] == agent_id)

    def rooms_of(self, agent_id: str) -> list[dict[str, Any]]:
        return [r for r in self.plan["rooms"] if r["agent"] == agent_id]

    def agent_state(self, agent_id: str, *, short: bool = False) -> str:
        if agent_id == self.host_id:
            return f"awake ({self.host_state})"
        working = next((j for j in self.jobs if j.agent == agent_id and j.status == "working"), None)
        queued = sum(1 for j in self.jobs if j.agent == agent_id and j.status == "queued")
        later = f", {queued} more waiting" if queued else ""
        if working is not None:
            doing = "waiting for the owner's yes on" if agent_id in self.waiting else "working on"
            room = next((r["name"] for r in self.plan["rooms"] if r["id"] == working.room), None)
            where = f" in the {room}" if room else ""
            return f'{doing} job {working.id}, "{working.title}"{where}{later}'
        if queued:
            return f"free, with {queued} job{'s' if queued != 1 else ''} waiting to start"
        return "free to take work"

    def room_jobs(self, room_id: str) -> list[Job]:
        return [j for j in self.jobs if j.room == room_id]

    def role(self, agent: dict[str, Any]) -> str:
        persona = agent.get("persona")
        return self.personas.get(persona).role if isinstance(persona, str) and persona else ""


# ---------------------------------------------------------------- the context lines


def summary(view: HouseView) -> str:
    """A few current lines for the start of a turn: who runs what, and the limits."""
    lines = [
        "Where you are now (house_overview, room_details and assistant_status tell more):",
        f"- You are {view.name}, the host. You orchestrate from the Hall and run no other room.",
    ]
    for a in view.plan["agents"]:
        if a["id"] == view.host_id:
            continue
        role = view.role(a)
        rooms = ", ".join(r["name"] for r in view.rooms_of(a["id"])) or "no room"
        who = f"{a['name']}, the {role}" if role else a["name"]
        lines.append(f"- {who} ({a['model']}): {rooms}; {view.agent_state(a['id'], short=True)}.")
    lines.append(f"- {limits.limits_line(view.project_tools)}")
    return "\n".join(lines)


# ---------------------------------------------------------------- the overview tool


def overview(view: HouseView) -> str:
    plan = view.plan
    rooms = plan["rooms"]
    extras = sum(1 for r in rooms if r["kind"] == "extra")
    out = [
        f"{view.name}'s house: {len(rooms)} rooms ({len(rooms) - extras} default, {extras} extra; "
        f"room for {plan['max_extra_rooms'] - extras} more extra).",
        "",
        "Rooms:",
    ]
    for r in rooms:
        agent = view.agent(r["agent"])
        project = f"project {r['project']}" if r["project"] else "no project"
        work = "".join(f'; job {j.id} "{j.title}" {j.status}' for j in view.room_jobs(r["id"]))
        out.append(f"- {r['name']} (id {r['id']}): run by {agent['name']}; light {r['state']}; {project}{work}.")
    out += ["", "Agents:"]
    for a in plan["agents"]:
        out.append(agent_block(view, a))
    out += ["", f"Limits: {limits.limits_line(view.project_tools)}"]
    return "\n".join(out)


def agent_block(view: HouseView, a: dict[str, Any]) -> str:
    persona = view.personas.get(a["persona"]) if a.get("persona") else None
    role = f", the {persona.role}" if persona and persona.role else ""
    models = a["model"] + (f" (heavy: {a['heavy_model']})" if a.get("heavy_model") else "")
    rooms = ", ".join(r["name"] for r in view.rooms_of(a["id"])) or "none"
    you = " This is you." if a["id"] == view.host_id else ""
    state = view.agent_state(a["id"])
    line = f"- {a['name']}{role} (id {a['id']}).{you} {state[:1].upper()}{state[1:]}. Model {models}. Rooms: {rooms}."
    if limits.can_take_work(a["id"]):
        line += f" At work it {limits.can_do(a['id'])}."
    if persona is not None:
        said = [f"{label}: {text}" for label, text in (("Looks after", persona.about), ("Manner", persona.manner), ("Work", persona.work)) if text]
        if said:
            line += "\n  Persona (in its own words, addressed to the agent): " + " ".join(said)
    return line


# ---------------------------------------------------------------- one room


def _plain(text: str) -> str:
    return " ".join(_FILLER.sub(" ", re.sub(r"[^a-z0-9 ]+", " ", text.lower())).split())


def find_room(plan: dict[str, Any], ref: str) -> dict[str, Any]:
    """The room called `ref`, by id or name, forgiving case, "the", "room" and small slips."""
    rooms: list[dict[str, Any]] = plan["rooms"]
    wanted = ref.strip().lower()
    for r in rooms:
        if wanted in (r["id"].lower(), r["name"].lower()):
            return r
    plain = _plain(ref)
    keys = {}
    for r in rooms:
        for key in {_plain(r["name"]), _plain(r["id"].replace("-", " "))}:
            if key:
                keys.setdefault(key, r)
    if plain in keys:
        return keys[plain]
    close = difflib.get_close_matches(plain, list(keys), n=1, cutoff=0.75)
    if close:
        return keys[close[0]]
    partial = {id(r): r for key, r in keys.items() if plain and (plain in key or key in plain)}
    if len(partial) == 1:
        return next(iter(partial.values()))
    names = ", ".join(r["name"] for r in rooms)
    raise NoSuchRoom(f"There is no room called {ref!r}. The rooms are: {names}.")


def room_details(view: HouseView, room: dict[str, Any], library: Sequence[LibraryEntry] | None) -> str:
    agent = view.agent(room["agent"])
    role = view.role(agent)
    kind = "one of the house's own rooms" if room["kind"] == "default" else "an extra room"
    who = f"{agent['name']}" + (f", the {role}" if role else "")
    out = [
        f"{room['name']} (id {room['id']}), {kind}, run by {who}: {view.agent_state(agent['id'])}.",
        f"Model here: {room['model']}. Project folder: {room['project'] or 'none'}. Light: {room['state']}.",
    ]
    tools = room["tools"]
    if tools:
        out.append("Tools:")
        for t in tools:
            here = "on this Mac" if t["available"] else "not installed on this Mac"
            if t["built_in"]:
                works = "works today"
            elif not limits.tool_works(False, view.project_tools):
                works = "stored; project tools are not installed in this build"
            elif not room["project"]:
                works = "runs only once the room has a project folder"
            else:
                works = "any resident working here can run it in the project folder, after the owner's yes"
            out.append(f"- {t['title']} ({t['id']}): {here}; {works}.")
    else:
        out.append("Tools: none.")
    work = view.room_jobs(room["id"])
    if work:
        out.append(
            "Jobs here now: "
            + "; ".join(f'{j.id} "{j.title}" by {view.agent(j.agent)["name"]} ({j.status})' for j in work)
            + "."
        )
    if library is not None:
        out.append(library_words(library))
    return "\n".join(out)


def library_words(entries: Sequence[LibraryEntry]) -> str:
    if not entries:
        return (
            "The shared library is empty: no notes yet. The owner adds Markdown files to "
            "house/library/ in the assistant's home. You read them yourself in every conversation, "
            "and the residents read them when they work."
        )
    lines = [f"The shared library holds {len(entries)} {'note' if len(entries) == 1 else 'notes'}:"]
    for e in entries:
        lines.append(f"- {e.title} ({e.path})" + (f": {e.gist}" if e.gist else ""))
    return "\n".join(lines)
