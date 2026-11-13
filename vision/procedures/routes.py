"""The owner's routes over every agent's procedures, mounted under `/api` behind the token.

- `GET /procedures`: `{agents: [{id, name, procedures}], shared, limits}`, each
  procedure a summary (`Procedure.summary`), each list by title.
- `GET /procedures/{owner}/{name}`: `{procedure}`, the summary with its steps.
  `owner` is an agent id or `shared`.
- `PUT /procedures/{owner}/{name}`: `{title?, when?, steps?}`, the owner's edit
  by hand of any procedure, shared ones too. Answers `{procedure}`.
- `DELETE /procedures/{owner}/{name}`: answers `{removed: true}`.

A refusal is a 400 with a line for people; an unknown procedure a 404.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from vision.core.server import require_token
from vision.procedures.store import (
    NAME_MAX,
    OWN_MAX,
    SHARED_MAX,
    STEPS_MAX,
    WHEN_MAX,
    NoSuchProcedure,
    ProcedureError,
    Procedures,
)

LIMITS = {"name": NAME_MAX, "when": WHEN_MAX, "steps": STEPS_MAX, "per_agent": OWN_MAX, "shared": SHARED_MAX}
FIELDS = ("title", "when", "steps")


def build_router(store: Procedures, agents: Callable[[], list[dict[str, Any]]]) -> APIRouter:
    """`agents()` gives the plan's agents (`[{id, name, ...}]`), read on every listing so renames show."""
    router = APIRouter(dependencies=[Depends(require_token)])

    async def run(call: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return await asyncio.to_thread(call, *args, **kwargs)
        except NoSuchProcedure as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except ProcedureError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    @router.get("/procedures")
    async def listing() -> dict[str, Any]:
        plan = [a for a in agents() if isinstance(a.get("id"), str)]
        own, shared = await run(store.everything, [a["id"] for a in plan])
        return {
            "agents": [
                {
                    "id": a["id"],
                    "name": str(a.get("name") or a["id"]),
                    "procedures": [p.summary() for p in own.get(a["id"], [])],
                }
                for a in plan
            ],
            "shared": [p.summary() for p in shared],
            "limits": LIMITS,
        }

    @router.get("/procedures/{owner}/{name}")
    async def read(owner: str, name: str) -> dict[str, Any]:
        found = await run(store.get, owner, name)
        return {"procedure": found.as_dict()}

    @router.put("/procedures/{owner}/{name}")
    async def edit(owner: str, name: str, request: Request) -> dict[str, Any]:
        body = await _body(request)
        changes = {k: body[k] for k in FIELDS if body.get(k) is not None}
        if any(not isinstance(v, str) for v in changes.values()):
            raise HTTPException(status_code=400, detail="The title, when and steps must be text.")
        edited = await run(store.edit, owner, name, **changes)
        return {"procedure": edited.as_dict()}

    @router.delete("/procedures/{owner}/{name}")
    async def delete(owner: str, name: str) -> dict[str, Any]:
        await run(store.delete, owner, name)
        return {"removed": True}

    return router


async def _body(request: Request) -> dict[str, Any]:
    try:
        body = json.loads(await request.body() or b"{}")
    except ValueError:
        raise HTTPException(status_code=400, detail="The body must be a JSON object.") from None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="The body must be a JSON object.")
    return body
