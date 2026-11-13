"""The live house: the plan, changes from the API, and hand edits to the file."""

from __future__ import annotations

import asyncio
import contextlib
import copy
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, get_args

from fastapi import APIRouter

from vision.core import effort
from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.events import HouseChanged, Notice, RoomLight
from vision.house import grid, store
from vision.house.folders import check_new
from vision.house.model import (
    CELL_M,
    HALL,
    HOST,
    MAX_EXTRA_ROOMS,
    MAX_ROOM_FOLDERS,
    WALL_HEIGHT_M,
    HouseError,
    Layout,
)
from vision.house.parse import build_layout
from vision.house.routes import build_router
from vision.house.tools import tool_refs

log = logging.getLogger(__name__)

POLL_S = 1.0
ADD_KEYS = {"id", "name", "at", "size", "agent", "model", "folders", "floor", "wall", "tools"}
EDIT_KEYS = {"name", "agent", "model", "folders", "floor", "wall", "at", "size", "tools"}
CLEARABLE = {"model", "folders", "tools"}
AGENT_EDIT_KEYS = {"name", "model", "effort", "heavy_effort"}

Mutation = Callable[[dict[str, Any], Layout], str | None]
"""Edits the user's document in place; returns the id of the room to report, if any."""


class GridHouse:
    """Implements `vision.core.interfaces.House` on a square grid of rooms.

    Nothing is read until `start()`, the first `plan()` or the first change.
    `start()` loads the files and starts watching the user's file for hand
    edits (a plan or change made inside the running loop starts it too);
    `close()` stops it.
    """

    def __init__(
        self,
        config: Config,
        bus: Bus,
        *,
        poll_s: float = POLL_S,
        default_file: Path = store.DEFAULT_FILE,
    ) -> None:
        self._config = config
        self._bus = bus
        self._poll_s = poll_s
        self._default_file = default_file
        self._path = config.paths.house_file
        self._default: dict[str, Any] = {}
        self._user: dict[str, Any] = {}
        self._layout: Layout | None = None
        self._stamp: store.Stamp | None = None
        self._broken: str | None = None
        self._pending: list[Notice] = []
        self._states: dict[str, RoomLight] = {}
        self._revision = 0
        self._lock = asyncio.Lock()
        self._watcher: asyncio.Task[None] | None = None
        self._router = build_router(self)

    # ------------------------------------------------------------ House protocol

    def plan(self) -> dict[str, Any]:
        layout = self._load()
        self._watch_lazily()
        occ = grid.occupancy(layout.rooms)
        agents = layout.agents
        return {
            "revision": self._revision,
            "cell_m": CELL_M,
            "wall_height_m": WALL_HEIGHT_M,
            "max_extra_rooms": MAX_EXTRA_ROOMS,
            "max_room_folders": MAX_ROOM_FOLDERS,
            "assistant": {"name": self._config.assistant.name},
            "agents": [
                {
                    "id": a.id,
                    "name": a.name,
                    "model": a.model,
                    "heavy_model": a.heavy_model,
                    "effort": a.effort,
                    "heavy_effort": a.heavy_effort,
                    "persona": a.persona,
                }
                for a in agents.values()
            ],
            "effort_levels": effort.table(
                [m for a in agents.values() for m in (a.model, a.heavy_model) if m]
                + [r.model for r in layout.rooms if r.model]
            ),
            "rooms": [
                {
                    "id": r.id,
                    "name": r.name,
                    "kind": r.kind,
                    "shape": r.shape,
                    "at": list(r.at),
                    "size": list(r.size),
                    "agent": r.agent,
                    "model": r.model or agents[r.agent].model,
                    "folders": list(r.folders),
                    "floor": r.floor,
                    "wall": r.wall,
                    "tools": tool_refs(agents[r.agent].tools if r.tools is None else r.tools),
                    "state": self._states.get(r.id, "idle" if r.id == HALL else "dark"),
                }
                for r in layout.rooms
            ],
            "doors": grid.doors(layout.rooms, occ),
            "free_slots": [list(c) for c in grid.free_slots(occ)],
        }

    @property
    def router(self) -> APIRouter:
        return self._router

    # ------------------------------------------------------------ for the daemon

    @property
    def revision(self) -> int:
        return self._revision

    async def start(self) -> None:
        """Load the house and start watching the file; a broken file becomes a notice."""
        await asyncio.to_thread(self._load)
        self._watch_lazily()

    def set_room_state(self, room_id: str, state: RoomLight) -> None:
        """Record a room's light (`dark`, `idle`, `active`) for the plan.

        Does not publish; the caller announces it with a `room.state` event.
        """
        if state not in get_args(RoomLight):
            raise HouseError(f"Room state must be one of {', '.join(get_args(RoomLight))}.")
        self._load().room(room_id)
        self._states[room_id] = state

    async def close(self) -> None:
        """Stop watching the file."""
        if self._watcher is not None:
            self._watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._watcher
            self._watcher = None

    # ------------------------------------------------------------ changes

    async def add_room(self, fields: dict[str, Any]) -> dict[str, Any]:
        """Add an extra room; returns it as it appears in the plan."""

        def mutate(doc: dict[str, Any], layout: Layout) -> str | None:
            _check_keys(fields, ADD_KEYS)
            if fields.get("id") in {r.id for r in layout.rooms}:
                raise HouseError(f"Room id {fields['id']!r} is already taken; ids must be unique.")
            _check_new_folders(fields, (), f"Room {fields.get('name', fields.get('id', '?'))!r}")
            entry = {k: v for k, v in fields.items() if v is not None}
            doc.setdefault("rooms", []).append(entry)
            return None

        return await self._change(mutate)

    async def update_room(self, room_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        """Rename, reassign, re-texture or (extra rooms only) move or resize a room."""

        def mutate(doc: dict[str, Any], layout: Layout) -> str | None:
            room = layout.room(room_id)
            _check_keys(fields, EDIT_KEYS)
            if not fields:
                raise HouseError("Nothing to change: send at least one setting.")
            if room.kind == "default" and {"at", "size"} & fields.keys():
                raise HouseError(
                    f"'{room.name}' is a default room: it can be renamed, reassigned and "
                    "re-textured, but not moved or resized."
                )
            _check_new_folders(fields, room.folders, f"Room {room.name!r}")
            entry = _entry(doc, room_id)
            for key, value in fields.items():
                if value is None and key in CLEARABLE:
                    entry.pop(key, None)
                elif value is None:
                    raise HouseError(f"{key} cannot be empty.")
                else:
                    entry[key] = value
            return room_id

        return await self._change(mutate)

    async def remove_room(self, room_id: str) -> None:
        """Remove an extra room, unless that would cut another room off from the Hall."""

        def mutate(doc: dict[str, Any], layout: Layout) -> str | None:
            room = layout.room(room_id)
            if room.kind == "default":
                raise HouseError(f"'{room.name}' is a default room and cannot be removed.")
            rest = [r for r in layout.rooms if r.id != room_id]
            reached = grid.paths_to_hall(rest, grid.occupancy(rest))
            stranded = [r.name for r in rest if r.id not in reached]
            if stranded:
                names = ", ".join(f"'{n}'" for n in stranded)
                raise HouseError(
                    f"Removing '{room.name}' would cut {names} off from the Hall. "
                    "Remove or move those rooms first."
                )
            doc["rooms"] = [t for t in doc.get("rooms", []) if t.get("id") != room_id]
            return None

        await self._change(mutate)

    async def update_agents(self, changes: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        """Rename agents or change their models in `[agents.<id>]` of the user's file.

        One write for every agent. The host's name and model are refused: they
        follow `[assistant] name` and `[brain] talk_model`. Returns the plan's agents.
        """

        def mutate(doc: dict[str, Any], layout: Layout) -> str | None:
            for agent_id, fields in changes.items():
                if agent_id not in layout.agents:
                    raise HouseError(f"There is no agent with the id {agent_id!r}.")
                if agent_id == HOST and AGENT_EDIT_KEYS & fields.keys():
                    raise HouseError(
                        "The host's name, model and effort follow the assistant's name, the talk "
                        "model and [brain] talk_effort; change those instead."
                    )
                _check_keys(fields, AGENT_EDIT_KEYS)
                doc.setdefault("agents", {}).setdefault(agent_id, {}).update(fields)
            return HALL

        await self._commit(mutate)
        return self.plan()["agents"]

    async def refresh(self) -> None:
        """Rebuild the plan from the loaded files and publish `house.changed`.

        For changes the house reads from config, such as `[assistant] name`.
        """
        async with self._lock:
            self._load()
            # `_user` is always the last document that built: a broken file never replaces it.
            self._apply(self._user, build_layout(self._default, self._user, self._config))

    async def reload(self) -> None:
        """Read the user's file again now, creating it from the default when it is missing."""
        async with self._lock:
            self._layout, self._broken, self._user = None, None, {}
            layout = await asyncio.to_thread(self._load)
            self._apply(self._user, layout)

    async def _change(self, mutate: Mutation) -> dict[str, Any]:
        target = await self._commit(mutate)
        return next(r for r in self.plan()["rooms"] if r["id"] == target)

    async def _commit(self, mutate: Mutation) -> str:
        """Apply `mutate` to a copy of the user's document, validate, write and publish.

        Returns the id of the room to report: the one `mutate` named, else the newest.
        """
        async with self._lock:
            layout = self._load()
            self._watch_lazily()
            if self._broken is not None:
                raise HouseError(
                    f"house.toml has an error, so the house cannot be changed until it is "
                    f"fixed: {self._broken}"
                )
            doc = copy.deepcopy(self._user)
            _pin(doc, layout)
            room_id = mutate(doc, layout)
            new = build_layout(self._default, doc, self._config)
            _pin(doc, new)
            self._stamp = await asyncio.to_thread(store.write_toml, self._path, doc)
            self._apply(doc, new)
            return room_id or new.rooms[-1].id

    def _apply(self, doc: dict[str, Any], layout: Layout) -> None:
        self._user = doc
        self._layout = layout
        ids = {r.id for r in layout.rooms}
        self._states = {k: v for k, v in self._states.items() if k in ids}
        self._revision += 1
        self._bus.publish(HouseChanged(revision=self._revision))

    # ------------------------------------------------------------ loading and watching

    def _load(self) -> Layout:
        """Load both files once. A broken user file falls back to the default house."""
        if self._layout is not None:
            return self._layout
        self._default = store.read_toml(self._default_file)
        fallback = build_layout(self._default, {}, self._config)
        store.ensure_user_file(self._path, self._default_file)
        self._stamp = store.stamp(self._path)
        try:
            doc = store.read_toml(self._path)
            layout = build_layout(self._default, doc, self._config)
        except HouseError as exc:
            self._reject(str(exc), "Using the default house until it is fixed.")
            layout = fallback
        else:
            self._user = doc
        self._layout = layout
        return layout

    def _watch_lazily(self) -> None:
        if self._watcher is not None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._watcher = loop.create_task(self._watch(), name="house-watch")

    async def _watch(self) -> None:
        for notice in self._pending:
            self._bus.publish(notice)
        self._pending.clear()
        while True:
            await asyncio.sleep(self._poll_s)
            try:
                await self._check_file()
            except Exception:
                log.exception("checking the house file failed")

    async def _check_file(self) -> None:
        async with self._lock:
            current = await asyncio.to_thread(store.stamp, self._path)
            if current is None or current == self._stamp:
                return
            self._stamp = current
            try:
                doc = await asyncio.to_thread(store.read_toml, self._path)
                layout = build_layout(self._default, doc, self._config)
            except HouseError as exc:
                self._reject(str(exc), "The house stays as it was.")
                return
            self._broken = None
            if doc != self._user:
                self._apply(doc, layout)

    def _reject(self, reason: str, outcome: str) -> None:
        self._broken = reason
        notice = Notice(level="warn", text=f"Your house.toml was not applied. {reason} {outcome}")
        log.warning("%s", notice.text)
        if self._watcher is None:
            self._pending.append(notice)  # published once watching starts on the loop
        else:
            self._bus.publish(notice)


def _check_keys(fields: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(fields) - allowed)
    if unknown:
        raise HouseError(f"Unknown setting {unknown[0]!r}. Allowed: {', '.join(sorted(allowed))}.")


def _entry(doc: dict[str, Any], room_id: str) -> dict[str, Any]:
    """The user's table for a room, created for a default room the file does not list."""
    rooms: list[dict[str, Any]] = doc.setdefault("rooms", [])
    for table in rooms:
        if table.get("id") == room_id:
            return table
    table = {"id": room_id}
    rooms.append(table)
    return table


def _check_new_folders(fields: dict[str, Any], before: tuple[str, ...], where: str) -> None:
    """Folders added through the routes must exist; the shape is left for the house to check."""
    value = fields.get("folders")
    if isinstance(value, list) and all(isinstance(f, str) for f in value):
        check_new([f.strip() for f in value], before, where)


def _pin(doc: dict[str, Any], layout: Layout) -> None:
    """Write the id and position the layout gave each extra room into its table.

    Extra rooms in the document and in the layout are in the same order.
    """
    defaults = {r.id for r in layout.rooms if r.kind == "default"}
    tables = [t for t in doc.get("rooms", []) if t.get("id") not in defaults]
    for table, room in zip(tables, layout.extras(), strict=True):
        table.setdefault("id", room.id)
        table.setdefault("at", list(room.at))
