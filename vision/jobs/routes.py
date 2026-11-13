"""The job routes, mounted by the core under `/api` behind the token.

- `GET /api/jobs?limit=50` (1 to 200): `{jobs, agents, limits}`, jobs newest
  first in the `job.changed` shape, and every resident's `agent.state`.
- `GET /api/jobs/{id}`: `{job}` with its brief, result, error, cost and steps.
- `POST /api/jobs`: the owner starts a job from the window (`agent`, `brief`,
  optional `room`, `title`, `careful`), with the same checks as `hand_off`.
- `POST /api/jobs/{id}/cancel`.

A refused request is a 400 whose `detail` is a line for people; an unknown
id is a 404.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from vision.core.server import require_token
from vision.jobs.board import MAX_ASKS, Board, JobError, NotFound
from vision.jobs.model import BRIEF_MAX, TITLE_MAX

FIELDS = frozenset({"agent", "brief", "room", "title", "careful"})


def build_router(board: Board) -> APIRouter:
    router = APIRouter(dependencies=[Depends(require_token)])

    @router.get("/jobs")
    async def listing(limit: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
        jobs = board.config.jobs
        return {
            "jobs": [j.summary() for j in board.all(limit)],
            "agents": board.agent_states(),
            "limits": {
                "max_running": jobs.max_running,
                "max_queued": jobs.max_queued,
                "max_steps": jobs.max_steps,
                "job_timeout_s": jobs.job_timeout_s,
                "max_job_usd": jobs.max_job_usd,
                "max_asks": MAX_ASKS,
                "brief_max": BRIEF_MAX,
                "title_max": TITLE_MAX,
            },
        }

    @router.get("/jobs/{job_id}")
    async def one(job_id: str) -> dict[str, Any]:
        job = board.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=str(NotFound(job_id)))
        return {"job": job.details()}

    @router.post("/jobs")
    async def start(request: Request) -> dict[str, Any]:
        body = await _body(request)
        unknown = sorted(set(body) - FIELDS)
        if unknown:
            raise HTTPException(status_code=400, detail=f"A job has no {unknown[0]!r}.")
        for key in ("room", "title"):
            if body.get(key) is not None and not isinstance(body[key], str):
                raise HTTPException(status_code=400, detail=f"{key} must be text.")
        if "careful" in body and not isinstance(body["careful"], bool):
            raise HTTPException(status_code=400, detail="careful must be true or false.")
        try:
            job = await board.hand_off(
                body.get("agent", ""),
                body.get("brief", ""),
                room=body.get("room"),
                title=body.get("title"),
                careful=body.get("careful", False),
                asked_by="owner",
                via="window",
            )
        except JobError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        return {"job": job.summary(), "started": job.status == "working"}

    @router.post("/jobs/{job_id}/cancel")
    async def cancel(job_id: str) -> dict[str, Any]:
        if board.get(job_id) is None:
            raise HTTPException(status_code=404, detail=str(NotFound(job_id)))
        try:
            job = await board.cancel(job_id)
        except JobError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        return {"job": job.summary()}

    return router


async def _body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    try:
        body = json.loads(raw) if raw else None
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="The body must be a JSON object.")
    return body
