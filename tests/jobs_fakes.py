"""A board on a plan of the default house, with scripted work: no model, no network."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from vision.core.bus import Bus
from vision.core.config import Config
from vision.core.events import RoomLight
from vision.jobs import Board, Desk, Job, Outcome
from vision.residents import BUDGET_USED

AGENTS = [
    ("host", "Vision"),
    ("steward", "Brass"),
    ("envoy", "Wren"),
    ("maker", "Tink"),
    ("checker", "Tock"),
    ("scout", "Rook"),
]
ROOMS = [
    ("hall", "Hall", "host"),
    ("library", "Library", "steward"),
    ("workshop", "Workshop", "maker"),
    ("garage", "Garage", "maker"),
    ("spare-room", "Spare Room", "checker"),
    ("attic", "Attic", "scout"),
    ("comms-room", "Comms Room", "envoy"),
]


def plan(folders: Sequence[str] = ()) -> dict[str, Any]:
    return {
        "assistant": {"name": "Vision"},
        "agents": [
            {
                "id": a,
                "name": n,
                "model": "claude-haiku-5-5",
                "heavy_model": "claude-opus-5-5" if a in ("checker", "host") else None,
                "persona": f"agents/{a}.md",
            }
            for a, n in AGENTS
        ],
        "rooms": [
            {
                "id": r,
                "name": n,
                "agent": a,
                "model": "claude-sonnet-5-5" if r == "workshop" else "claude-haiku-5-5",
                "folders": list(folders) if r == "workshop" else [],
                "tools": [{"id": "python", "title": "Python", "available": True, "built_in": False}]
                if r == "workshop"
                else [],
                "state": "idle" if r == "hall" else "dark",
            }
            for r, n, a in ROOMS
        ],
    }


Script = Callable[[Job, Desk], Awaitable[Outcome]]


class Scripted:
    """The board's work: each agent's script, or one that waits until released."""

    def __init__(self) -> None:
        self.scripts: dict[str, Script] = {}
        self.release: dict[str, asyncio.Event] = {}
        self.started: list[str] = []

    async def __call__(self, job: Job, desk: Desk) -> Outcome:
        self.started.append(job.id)
        script = self.scripts.get(job.agent)
        if script is not None:
            return await script(job, desk)
        gate = self.release.setdefault(job.id, asyncio.Event())
        await gate.wait()
        return Outcome("done", f"{job.agent} did {job.title}")

    def finish(self, job: Job) -> None:
        self.release.setdefault(job.id, asyncio.Event()).set()


class Spend:
    """The residents' refusal: the budget's words once `out` is set."""

    def __init__(self) -> None:
        self.out = False

    async def __call__(self) -> str | None:
        return BUDGET_USED if self.out else None


async def make_board(config: Config, bus: Bus | None = None, folders: Sequence[str] = ()) -> tuple[Board, Scripted, Spend, dict[str, RoomLight]]:
    lights: dict[str, RoomLight] = {}
    spend = Spend()
    board = Board(
        config,
        bus or Bus(),
        plan=lambda: plan(folders),
        refusal=spend,
        light=lambda room, light: lights.__setitem__(room, light),
    )
    work = Scripted()
    await board.start(work)
    return board, work, spend, lights
