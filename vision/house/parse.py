"""Turn the default file, the user's file and config into a validated `Layout`.

Merging: agents are merged key by key (default, then the user's house file,
then `[agents.<id>]` in config.toml). A user room whose id matches a default
room overrides its fields; any other user room is an extra room. Default
rooms keep their place and shape whatever the user's file says.
"""

from __future__ import annotations

import re
from typing import Any

from vision.core.config import Config
from vision.house import grid
from vision.house.model import (
    EXTRA_FLOOR,
    EXTRA_WALL,
    HALL,
    HOST,
    MAX_EXTRA_CELLS,
    MAX_EXTRA_ROOMS,
    TEXTURES,
    Agent,
    Cell,
    HouseError,
    Layout,
    Room,
    RoomKind,
)
from vision.house.tools import check_tool_ids, with_built_ins

SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
TOP_KEYS = {"agents", "rooms"}
AGENT_KEYS = {"name", "persona", "model", "heavy_model", "tools"}
ROOM_KEYS = {
    "id",
    "name",
    "at",
    "size",
    "shape",
    "agent",
    "model",
    "project",
    "floor",
    "wall",
    "tools",
}
PLACE_KEYS = ("at", "size", "shape")


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def build_layout(default: dict[str, Any], user: dict[str, Any], config: Config) -> Layout:
    """Merge and validate. Raises `HouseError` naming the first broken rule."""
    agents = build_agents(default, user, config)
    rooms = _build_rooms(default, user, agents)
    return Layout(agents=agents, rooms=rooms)


def build_agents(default: dict[str, Any], user: dict[str, Any], config: Config) -> dict[str, Agent]:
    for doc in (default, user):
        unknown = set(doc) - TOP_KEYS
        if unknown:
            raise HouseError(
                f"Unknown section {min(unknown)!r} in the house file; "
                "only [agents.<id>] and [[rooms]] are allowed."
            )
    tables: dict[str, dict[str, Any]] = {}
    for source, layer in (
        ("the house file", default.get("agents", {})),
        ("the house file", user.get("agents", {})),
        ("config.toml", config.agents),
    ):
        if not isinstance(layer, dict):
            raise HouseError(f"[agents] in {source} must be a table of agents.")
        for agent_id, table in layer.items():
            if not isinstance(table, dict):
                raise HouseError(f"[agents.{agent_id}] in {source} must be a table.")
            tables[agent_id] = {**tables.get(agent_id, {}), **table}
    return {agent_id: _agent(agent_id, table, config) for agent_id, table in tables.items()}


def _agent(agent_id: str, table: dict[str, Any], config: Config) -> Agent:
    where = f"Agent {agent_id!r}"
    if not SLUG.match(agent_id):
        raise HouseError(f"{where}: ids use lowercase letters, digits and dashes.")
    _no_unknown_keys(table, AGENT_KEYS, where)
    is_host = agent_id == HOST
    name = _text(table, "name", where, required=not is_host) or config.assistant.name
    persona = _text(table, "persona", where, required=True)
    model = _text(table, "model", where, required=not is_host) or config.brain.talk_model
    heavy = _text(table, "heavy_model", where, required=False)
    if heavy is None and is_host:
        heavy = config.brain.heavy_model
    tools = check_tool_ids(table["tools"], where) if "tools" in table else ()
    if is_host:
        tools = with_built_ins(tools)
    assert persona is not None
    return Agent(
        id=agent_id, name=name, persona=persona, model=model, heavy_model=heavy, tools=tools
    )


def _build_rooms(
    default: dict[str, Any], user: dict[str, Any], agents: dict[str, Agent]
) -> list[Room]:
    base = _room_tables(default.get("rooms", []), "default.toml")
    defaults: dict[str, dict[str, Any]] = {t["id"]: t for t in base}
    if HALL not in defaults:
        raise HouseError("The default house has no Hall.")
    overrides: dict[str, dict[str, Any]] = {}
    extra_tables: list[dict[str, Any]] = []
    for table in _room_tables(user.get("rooms", []), "house.toml"):
        room_id = table.get("id")
        if isinstance(room_id, str) and room_id in defaults:
            if room_id in overrides:
                raise HouseError(f"Room id {room_id!r} appears twice in house.toml.")
            _keep_place(defaults[room_id], table)
            overrides[room_id] = table
        else:
            extra_tables.append(table)

    rooms = [_room({**t, **overrides.get(t["id"], {})}, "default", agents) for t in base]
    if len(extra_tables) > MAX_EXTRA_ROOMS:
        raise HouseError(
            f"The house can hold at most {MAX_EXTRA_ROOMS} extra rooms "
            f"and this would make {len(extra_tables)}. Remove one first."
        )
    taken = {r.id for r in rooms}
    named: list[dict[str, Any]] = []
    for table in extra_tables:
        room_id = _extra_id(table, taken)
        taken.add(room_id)
        named.append({**table, "id": room_id})
    return _place_extras(rooms, named, agents)


def _place_extras(
    rooms: list[Room], tables: list[dict[str, Any]], agents: dict[str, Agent]
) -> list[Room]:
    """Explicitly placed rooms first, then the rest into the free spot nearest the Hall."""
    placed: dict[int, Room] = {}
    for i, table in enumerate(tables):
        if "at" in table:
            placed[i] = _room(table, "extra", agents)
    occ = grid.occupancy([*rooms, *placed.values()])
    hall = next(r for r in rooms if r.id == HALL)
    for i, table in enumerate(tables):
        if i in placed:
            continue
        size = _size(table, f"Room {table.get('name', table['id'])!r}")
        room = _room({**table, "at": list(grid.nearest_spot(occ, size, hall))}, "extra", agents)
        for cell in room.cells():
            occ[cell] = room.id
        placed[i] = room
    all_rooms = [*rooms, *(placed[i] for i in range(len(tables)))]
    reached = grid.paths_to_hall(all_rooms, occ)
    for room in all_rooms:
        if room.id not in reached:
            raise HouseError(
                f"Room '{room.name}' at [{room.at[0]}, {room.at[1]}] must share a wall "
                "(an edge, not just a corner) with a room already in the house."
            )
    return all_rooms


def _room(table: dict[str, Any], kind: RoomKind, agents: dict[str, Agent]) -> Room:
    room_id = table["id"]
    where = f"Room {table.get('name', room_id)!r}"
    name = _text(table, "name", where, required=True)
    agent = table.get("agent")
    if not isinstance(agent, str):
        raise HouseError(f'{where} must name exactly one agent, as text: agent = "host".')
    if agent not in agents:
        known = ", ".join(agents)
        raise HouseError(f"{where} names agent {agent!r}, which is not one of: {known}.")
    _check_host_rule(room_id, where, agent, agents)
    shape = table.get("shape", "rect")
    if shape not in ("rect", "round") or (kind == "extra" and shape != "rect"):
        raise HouseError(f'{where}: shape must be "rect"; only the Attic is round.')
    size = _size(table, where)
    if kind == "extra" and size[0] * size[1] > MAX_EXTRA_CELLS:
        raise HouseError(f"{where} covers {size[0] * size[1]} cells; a room may cover 1 to 4.")
    if "at" not in table:
        raise HouseError(f"{where} needs a position: at = [column, row].")
    floor = _texture(table, "floor", where, EXTRA_FLOOR if kind == "extra" else None)
    wall = _texture(table, "wall", where, EXTRA_WALL if kind == "extra" else None)
    assert name is not None
    return Room(
        id=room_id,
        name=name,
        kind=kind,
        shape=shape,
        at=_pair(table["at"], where, "at", minimum=None),
        size=size,
        agent=agent,
        model=_text(table, "model", where, required=False),
        project=_text(table, "project", where, required=False),
        floor=floor,
        wall=wall,
        tools=check_tool_ids(table["tools"], where) if "tools" in table else None,
    )


def _check_host_rule(room_id: str, where: str, agent: str, agents: dict[str, Agent]) -> None:
    """The host runs the Hall and nothing else."""
    host = agents[HOST].name
    if room_id == HALL and agent != HOST:
        raise HouseError(
            f"{host} orchestrates from the Hall, so the Hall cannot be given to another agent."
        )
    if room_id != HALL and agent == HOST:
        others = ", ".join(a.name for a in agents.values() if a.id != HOST)
        raise HouseError(
            f"{host} orchestrates from the Hall and cannot run another room. "
            f"Choose one of: {others}."
        )


def _room_tables(value: Any, source: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(t, dict) for t in value):
        raise HouseError(f"Rooms in {source} must be [[rooms]] tables.")
    for table in value:
        _no_unknown_keys(table, ROOM_KEYS, f"Room {table.get('name', table.get('id', '?'))!r}")
    return value


def _keep_place(default: dict[str, Any], table: dict[str, Any]) -> None:
    for key in PLACE_KEYS:
        if key in table and table[key] != default.get(key, _place_default(key)):
            raise HouseError(
                f"'{default['name']}' is a default room: it can be renamed, reassigned and "
                f"re-textured, but not moved or reshaped. Remove {key!r} from it in house.toml."
            )


def _place_default(key: str) -> Any:
    return {"size": [1, 1], "shape": "rect"}.get(key)


def _extra_id(table: dict[str, Any], taken: set[str]) -> str:
    given = table.get("id")
    if given is not None:
        if not isinstance(given, str) or not SLUG.match(given):
            raise HouseError(f"Room id {given!r}: use lowercase letters, digits and dashes.")
        if given in taken:
            raise HouseError(f"Room id {given!r} is already taken; ids must be unique.")
        return given
    name = table.get("name")
    base = slugify(name) if isinstance(name, str) else ""
    if not base:
        raise HouseError(f"Room {name!r} needs a name with letters or digits.")
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base}-{n}", n + 1
    return candidate


def _no_unknown_keys(table: dict[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise HouseError(
            f"{where}: unknown setting {unknown[0]!r}. Allowed: {', '.join(sorted(allowed))}."
        )


def _text(table: dict[str, Any], key: str, where: str, *, required: bool) -> str | None:
    value = table.get(key)
    if value is None:
        if required:
            raise HouseError(f"{where} needs a {key}.")
        return None
    if not isinstance(value, str) or not value.strip():
        raise HouseError(f"{where}: {key} must be non-empty text.")
    return value.strip()


def _texture(table: dict[str, Any], key: str, where: str, fallback: str | None) -> str:
    value = table.get(key, fallback)
    if value not in TEXTURES:
        raise HouseError(f"{where}: {key} must be one of {', '.join(TEXTURES)}, not {value!r}.")
    return str(value)


def _size(table: dict[str, Any], where: str) -> Cell:
    return _pair(table.get("size", [1, 1]), where, "size", minimum=1)


def _pair(value: Any, where: str, key: str, *, minimum: int | None) -> Cell:
    ok = (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(v, int) and not isinstance(v, bool) for v in value)
        and (minimum is None or min(value) >= minimum)
    )
    if not ok:
        hint = "two whole numbers of at least 1" if minimum else "two whole numbers"
        raise HouseError(f"{where}: {key} must be {hint}, like [1, 2]; got {value!r}.")
    return value[0], value[1]
