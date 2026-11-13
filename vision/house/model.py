"""The house's data: agents, rooms and the limits that bind them."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Cell = tuple[int, int]
"""A grid cell as (column, row); columns grow east, rows grow south."""

RoomKind = Literal["default", "extra"]
RoomShape = Literal["rect", "round"]

HALL = "hall"
HOST = "host"
CELL_M = 4.0
WALL_HEIGHT_M = 2.6
MAX_EXTRA_ROOMS = 20
MAX_EXTRA_CELLS = 4
MAX_ROOM_FOLDERS = 8
MAX_PROJECT_NAME = 60
TEXTURES = (
    "wallpaper",
    "teal-panel",
    "wood-floor",
    "red-carpet",
    "pale-stone",
    "roof-shingle",
    "stone-tile",
)
"""Texture names, matching the files in `assets/textures/`."""
EXTRA_FLOOR = "wood-floor"
EXTRA_WALL = "wallpaper"


def rect(at: Cell, size: Cell) -> list[Cell]:
    """The cells of a `size` rectangle whose north-west corner is `at`, row by row."""
    return [(at[0] + i, at[1] + j) for j in range(size[1]) for i in range(size[0])]


class HouseError(ValueError):
    """A house file or a change to the house breaks a rule. The message is for people."""


class UnknownRoom(LookupError):
    """No room has the requested id."""

    def __init__(self, room_id: str) -> None:
        super().__init__(f"There is no room with the id {room_id!r}.")
        self.room_id = room_id

    def __str__(self) -> str:
        return str(self.args[0])


@dataclass(frozen=True, slots=True)
class Agent:
    id: str
    name: str
    persona: str
    model: str
    heavy_model: str | None
    effort: str = "medium"
    """Claude's thinking effort at work (`vision.core.effort`); the host's follows `[brain]`."""
    heavy_effort: str = "high"
    """The effort of a careful job (on the heavy model when there is one)."""
    tools: tuple[str, ...] = ()
    """Tool ids for the agent's rooms that list none of their own."""


@dataclass(frozen=True, slots=True)
class Room:
    id: str
    name: str
    kind: RoomKind
    shape: RoomShape
    at: Cell
    size: Cell
    agent: str
    model: str | None
    """The room's own model, overriding its agent's; None to use the agent's."""
    folders: tuple[str, ...]
    """The room's project folders, in order, as the owner wrote them (`~/Projects/shop`)."""
    floor: str
    wall: str
    tools: tuple[str, ...] | None = None
    """The room's own tool ids; None to use the agent's."""
    project: str | None = None
    """What the owner calls the project the room holds (`Harbor Books`); None when unnamed."""

    def cells(self) -> list[Cell]:
        return rect(self.at, self.size)


@dataclass(frozen=True, slots=True)
class Layout:
    """A validated house: every rule in spec 4.8 holds."""

    agents: dict[str, Agent]
    rooms: list[Room]

    def room(self, room_id: str) -> Room:
        for room in self.rooms:
            if room.id == room_id:
                return room
        raise UnknownRoom(room_id)

    def extras(self) -> list[Room]:
        return [r for r in self.rooms if r.kind == "extra"]
