"""House routes, mounted by the core under `/api/house` behind the token."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from vision.core.server import require_token
from vision.house.model import HouseError, UnknownRoom
from vision.house.tools import catalog_entries, propose_tools, tool_refs

if TYPE_CHECKING:
    from vision.house.house import GridHouse


def build_router(house: GridHouse) -> APIRouter:
    router = APIRouter(dependencies=[Depends(require_token)])

    @router.get("/agents")
    async def agents() -> dict[str, Any]:
        return {"agents": house.plan()["agents"]}

    @router.get("/tools")
    async def tools() -> dict[str, Any]:
        return {"tools": await asyncio.to_thread(catalog_entries)}

    @router.get("/tools/propose")
    async def propose(project: str = Query(..., min_length=1)) -> dict[str, Any]:
        path = Path(project).expanduser()
        try:
            ids = await asyncio.to_thread(propose_tools, path)
        except NotADirectoryError:
            raise HTTPException(status_code=400, detail=f"{project} is not a folder.") from None
        return {"project": str(path), "tools": await asyncio.to_thread(tool_refs, ids)}

    @router.post("/rooms", status_code=201)
    async def add_room(request: Request) -> dict[str, Any]:
        room = await _run(house.add_room(await _body(request)))
        return {"revision": house.revision, "room": room}

    @router.patch("/rooms/{room_id}")
    async def update_room(room_id: str, request: Request) -> dict[str, Any]:
        room = await _run(house.update_room(room_id, await _body(request)))
        return {"revision": house.revision, "room": room}

    @router.delete("/rooms/{room_id}")
    async def remove_room(room_id: str) -> dict[str, Any]:
        await _run(house.remove_room(room_id))
        return {"revision": house.revision}

    return router


async def _body(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="The body must be a JSON object.") from None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="The body must be a JSON object.")
    return body


async def _run[T](change: Awaitable[T]) -> T:
    try:
        return await change
    except UnknownRoom as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except HouseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
