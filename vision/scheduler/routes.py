"""The automation routes, mounted by the core under `/api` behind the token.

- `GET /api/automations`: the list, the limits, and the time zone.
- `POST /api/automations`: create one (`name`, `schedule`, `instruction`,
  optional `speak` and `paused`).
- `PATCH /api/automations/{id}`: change any of those fields.
- `DELETE /api/automations/{id}`.
- `POST /api/automations/{id}/run`: run it now, outside its schedule.

A refused change is a 400 whose `detail` is a line for people; an unknown id
is a 404.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from vision.core.localtime import zone_name
from vision.core.server import require_token
from vision.scheduler.model import INSTRUCTION_MAX, MAX_AUTOMATIONS, NAME_MAX
from vision.scheduler.service import AutomationError, Automations, NotFound


def build_router(automations: Automations) -> APIRouter:
    router = APIRouter(dependencies=[Depends(require_token)])

    @router.get("/automations")
    async def listing() -> dict[str, Any]:
        return {
            "automations": [automations.view(a) for a in automations.all()],
            "limits": {
                "max_automations": MAX_AUTOMATIONS,
                "name_max": NAME_MAX,
                "instruction_max": INSTRUCTION_MAX,
            },
            "timezone": zone_name(automations.zone()),
            "now": automations.clock.now(),
        }

    @router.post("/automations")
    async def create(request: Request) -> dict[str, Any]:
        body = await _body(request)
        try:
            return {"automation": automations.view(await automations.create(body))}
        except AutomationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    @router.patch("/automations/{automation_id}")
    async def update(automation_id: str, request: Request) -> dict[str, Any]:
        body = await _body(request)
        _known(automations, automation_id)
        try:
            return {"automation": automations.view(await automations.update(automation_id, body))}
        except AutomationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    @router.delete("/automations/{automation_id}")
    async def delete(automation_id: str) -> dict[str, Any]:
        _known(automations, automation_id)
        return {"deleted": (await automations.delete(automation_id)).id}

    @router.post("/automations/{automation_id}/run")
    async def run(automation_id: str) -> dict[str, Any]:
        _known(automations, automation_id)
        return {"automation": automations.view(automations.request_run(automation_id)), "queued": True}

    return router


def _known(automations: Automations, automation_id: str) -> None:
    """Routes take ids only, never names."""
    if automations.get(automation_id) is None:
        raise HTTPException(status_code=404, detail=str(NotFound(automation_id)))


async def _body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    try:
        body = json.loads(raw) if raw else None
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="The body must be a JSON object.")
    return body
