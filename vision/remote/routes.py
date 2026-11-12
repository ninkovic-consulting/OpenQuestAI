"""The phone routes, mounted by the core under `/api` behind the token.

- `GET /api/phone`: the channel's state and settings (never the bot token).
- `PATCH /api/phone`: `enabled`, `speak_on_mac`, `voice_replies`,
  `notify: {automations, warnings, approvals}`, `phone_tools`.
- `POST /api/phone/token`: `{token}`; checked with Discord, then stored in
  the Keychain. Answers `{stored, verdict, bot}`.
- `POST /api/phone/token/verify`: `{verdict, bot}`.
- `POST /api/phone/pairing`: a new one-time code, `{code, expires_at}`.
- `DELETE /api/phone/pairing`: unpair (and void any code).

Bodies are read by hand, so a refused token is never echoed back in an error.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from vision.core.server import require_token
from vision.remote.service import Phone, Refused


def build_router(phone: Phone) -> APIRouter:
    router = APIRouter(dependencies=[Depends(require_token)])

    @router.get("/phone")
    async def view() -> dict[str, Any]:
        return await phone.view()

    @router.patch("/phone")
    async def update(request: Request) -> dict[str, Any]:
        try:
            return await phone.update(await _body(request))
        except Refused as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    @router.post("/phone/token")
    async def store_token(request: Request) -> dict[str, Any]:
        try:
            return await phone.store_token(await _body(request))
        except Refused as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    @router.post("/phone/token/verify")
    async def verify() -> dict[str, Any]:
        return await phone.verify()

    @router.post("/phone/pairing")
    async def pairing() -> dict[str, Any]:
        try:
            return phone.new_code()
        except Refused as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    @router.delete("/phone/pairing")
    async def unpair() -> dict[str, Any]:
        return await phone.unpair()

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
