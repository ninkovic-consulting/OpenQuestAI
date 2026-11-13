"""The owner's routes for proposals and made tools, mounted under `/api` behind the token.

These are the only way a proposal is approved, declined or put back, and the
only way a made tool is changed: no agent tool, gate request, phone button or
spoken or typed yes reaches them.

- `GET /proposals?limit=50` (1 to 200): `{proposals, waiting, limits}`, summaries,
  waiting oldest first, then decided newest first.
- `GET /proposals/{id}`: `{proposal}` with the script or the whole persona.
- `POST /proposals/{id}/approve` `{who?, tier?}` (tools only; default author, ask).
- `POST /proposals/{id}/decline` `{note?}`.
- `POST /proposals/{id}/restore`: put back what an approved change replaced.
- `GET /made-tools`: `{tools, confinement}`.
- `GET /made-tools/{name}`: `{tool, runs}`, every version's script included.
- `PATCH /made-tools/{name}` `{tier?, who?, enabled?}`: `{tool}`.
- `POST /made-tools/{name}/versions/{n}/use`: `{tool}`.
- `DELETE /made-tools/{name}`: `{removed: true}`.

A refusal is a 400 whose `detail` is a line for people; an unknown id or name a 404.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from vision.core.server import require_token
from vision.proposals.model import NotFound, ProposalError
from vision.proposals.service import Proposals


def build_router(proposals: Proposals) -> APIRouter:
    router = APIRouter(dependencies=[Depends(require_token)])

    @router.get("/proposals")
    async def listing(limit: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
        return {
            "proposals": [p.summary() for p in proposals.listing(limit)],
            "waiting": proposals.waiting_count(),
            "limits": proposals.limits(),
        }

    @router.get("/proposals/{proposal_id}")
    async def one(proposal_id: str) -> dict[str, Any]:
        return {"proposal": _sync(proposals.get, proposal_id).detail()}

    @router.post("/proposals/{proposal_id}/approve")
    async def approve(proposal_id: str, request: Request) -> dict[str, Any]:
        body = await _body(request, {"who", "tier"})
        done = await _do(proposals.approve(proposal_id, body.get("who", "author"), body.get("tier", "ask")))
        return {"proposal": done.detail()}

    @router.post("/proposals/{proposal_id}/decline")
    async def decline(proposal_id: str, request: Request) -> dict[str, Any]:
        body = await _body(request, {"note"})
        return {"proposal": (await _do(proposals.decline(proposal_id, body.get("note", "")))).detail()}

    @router.post("/proposals/{proposal_id}/restore")
    async def restore(proposal_id: str) -> dict[str, Any]:
        return {"proposal": (await _do(proposals.restore(proposal_id))).detail()}

    @router.get("/made-tools")
    async def made_list() -> dict[str, Any]:
        confinement = await asyncio.to_thread(proposals.confinement)
        return {"tools": proposals.made_list(), "confinement": confinement}

    @router.get("/made-tools/{name}")
    async def made_get(name: str) -> dict[str, Any]:
        return await _do(proposals.made_get(name))

    @router.patch("/made-tools/{name}")
    async def made_update(name: str, request: Request) -> dict[str, Any]:
        body = await _body(request, {"tier", "who", "enabled"})
        tool = await _do(
            proposals.made_update(name, tier=body.get("tier"), who=body.get("who"), enabled=body.get("enabled"))
        )
        return {"tool": tool}

    @router.post("/made-tools/{name}/versions/{n}/use")
    async def made_use(name: str, n: int) -> dict[str, Any]:
        return {"tool": await _do(proposals.made_use_version(name, n))}

    @router.delete("/made-tools/{name}")
    async def made_delete(name: str) -> dict[str, Any]:
        await _do(proposals.made_delete(name))
        return {"removed": True}

    return router


def _sync(call: Any, *args: Any) -> Any:
    try:
        return call(*args)
    except NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


async def _do[T](work: Awaitable[T]) -> T:
    try:
        return await work
    except NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ProposalError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


async def _body(request: Request, allowed: set[str]) -> dict[str, Any]:
    raw = await request.body()
    try:
        body = json.loads(raw) if raw.strip() else {}
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="The body must be a JSON object.")
    unknown = sorted(set(body) - allowed)
    if unknown:
        raise HTTPException(status_code=400, detail=f"{unknown[0]!r} is not something that can be set here.")
    return body
