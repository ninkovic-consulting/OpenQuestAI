"""Grid geometry: who is next to whom, doors, free slots and placement."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable

from vision.house.model import HALL, Cell, HouseError, Room, rect

SIDES: dict[str, Cell] = {"n": (0, -1), "e": (1, 0), "s": (0, 1), "w": (-1, 0)}


def step(cell: Cell, side: str) -> Cell:
    dx, dy = SIDES[side]
    return cell[0] + dx, cell[1] + dy


def occupancy(rooms: Iterable[Room]) -> dict[Cell, str]:
    """Map every covered cell to its room id. Raises on overlap."""
    occ: dict[Cell, str] = {}
    names: dict[str, str] = {}
    for room in rooms:
        names[room.id] = room.name
        for cell in room.cells():
            if cell in occ:
                raise HouseError(
                    f"Room '{room.name}' overlaps '{names[occ[cell]]}' at [{cell[0]}, {cell[1]}]."
                )
            occ[cell] = room.id
    return occ


def neighbours(rooms: list[Room], occ: dict[Cell, str]) -> dict[str, list[str]]:
    """Rooms that share a wall (an edge, not a corner), in room order."""
    order = {room.id: i for i, room in enumerate(rooms)}
    out: dict[str, list[str]] = {}
    for room in rooms:
        found = {
            other
            for cell in room.cells()
            for side in SIDES
            if (other := occ.get(step(cell, side))) is not None and other != room.id
        }
        out[room.id] = sorted(found, key=order.__getitem__)
    return out


def paths_to_hall(rooms: list[Room], occ: dict[Cell, str]) -> dict[str, str | None]:
    """Breadth-first from the Hall: each reachable room's next room toward it.

    The Hall maps to None; rooms cut off from the Hall are absent.
    """
    adj = neighbours(rooms, occ)
    parent: dict[str, str | None] = {HALL: None}
    queue = deque([HALL])
    while queue:
        current = queue.popleft()
        for other in adj[current]:
            if other not in parent:
                parent[other] = current
                queue.append(other)
    return parent


def doors(rooms: list[Room], occ: dict[Cell, str]) -> list[dict[str, object]]:
    """One door per room, on the shortest path toward the Hall.

    The door sits on an edge room `a` shares with `b`, the next room toward
    the Hall, given as one of `a`'s cells and that cell's side.
    """
    parent = paths_to_hall(rooms, occ)
    out: list[dict[str, object]] = []
    for room in rooms:
        toward = parent.get(room.id)
        if toward is None:
            continue
        edges = sorted(
            (cell, side)
            for cell in room.cells()
            for side in SIDES
            if occ.get(step(cell, side)) == toward
        )
        cell, side = edges[(len(edges) - 1) // 2]
        out.append({"a": room.id, "b": toward, "cell": [cell[0], cell[1]], "side": side})
    return out


def free_slots(occ: dict[Cell, str]) -> list[Cell]:
    """Every empty cell that shares an edge with the house, in reading order."""
    slots = {step(cell, side) for cell in occ for side in SIDES} - occ.keys()
    return sorted(slots, key=lambda c: (c[1], c[0]))


def nearest_spot(occ: dict[Cell, str], size: Cell, hall: Room) -> Cell:
    """The free position for a room of `size`, touching the house, nearest the Hall's centre."""
    w, d = size
    # Centres doubled to stay in integers.
    hx, hy = 2 * hall.at[0] + hall.size[0], 2 * hall.at[1] + hall.size[1]
    best: tuple[tuple[int, int, int], Cell] | None = None
    for fx, fy in free_slots(occ):
        for ox in range(w):
            for oy in range(d):
                at = (fx - ox, fy - oy)
                if any(c in occ for c in rect(at, size)):
                    continue
                cx, cy = 2 * at[0] + w, 2 * at[1] + d
                key = ((cx - hx) ** 2 + (cy - hy) ** 2, at[1], at[0])
                if best is None or key < best[0]:
                    best = (key, at)
    if best is None:
        raise HouseError(f"There is no free spot next to the house for a room of size [{w}, {d}].")
    return best[1]
