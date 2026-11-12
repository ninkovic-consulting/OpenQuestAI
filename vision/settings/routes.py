"""The settings routes, mounted by the core under `/api` behind the token.

Bodies are read by hand, not by pydantic models, so a refused value (the API
key above all) is never echoed back in an error.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from vision.core.server import require_token
from vision.settings import backups, folders
from vision.settings.downloads import WHATS
from vision.settings.reset import NAMES
from vision.settings.service import Refused, SettingsService
from vision.settings.values import Invalid


def build_router(service: SettingsService) -> APIRouter:
    router = APIRouter(dependencies=[Depends(require_token)])

    @router.get("/settings")
    async def get_settings() -> dict[str, Any]:
        return await service.settings()

    @router.patch("/settings")
    async def patch_settings(request: Request) -> dict[str, Any]:
        try:
            return await service.patch(await _body(request))
        except Invalid as exc:
            raise HTTPException(status_code=400, detail={"errors": exc.errors}) from None

    @router.post("/settings/key")
    async def store_key(request: Request) -> dict[str, Any]:
        return await _refusable(service.store_key(await _body(request)))

    @router.post("/settings/key/verify")
    async def verify_key() -> dict[str, Any]:
        return await service.verify_key()

    @router.get("/models")
    async def models() -> dict[str, Any]:
        return await service.models.listing(service.config)

    @router.get("/voice/devices")
    async def voice_devices() -> dict[str, Any]:
        return await asyncio.to_thread(service.voice.devices)

    @router.post("/voice")
    async def voice(request: Request) -> dict[str, Any]:
        enabled = (await _body(request)).get("enabled")
        if not isinstance(enabled, bool):
            raise HTTPException(status_code=400, detail="Send enabled as true or false.")
        await service.voice.switch(enabled)
        return await asyncio.to_thread(service.voice.state)

    @router.post("/voice/test")
    async def voice_test() -> dict[str, Any]:
        return await service.voice.test()

    @router.get("/downloads")
    async def downloads() -> dict[str, Any]:
        return await asyncio.to_thread(service.downloads.status)

    @router.post("/downloads")
    async def start_download(request: Request) -> dict[str, Any]:
        what = (await _body(request)).get("what")
        if what not in WHATS:
            raise HTTPException(
                status_code=400, detail=f"Choose what to download: {' or '.join(WHATS)}."
            )
        return await service.downloads.start(what)

    @router.get("/fs/dirs")
    async def dirs(prefix: str = Query(...)) -> dict[str, Any]:
        try:
            return {"dirs": await asyncio.to_thread(folders.list_dirs, prefix)}
        except folders.BadPrefix as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    @router.get("/doctor")
    async def doctor() -> dict[str, Any]:
        return await service.doctor()

    @router.post("/doctor/fix")
    async def fix(request: Request) -> dict[str, Any]:
        return await _refusable(service.fix((await _body(request)).get("id")))

    @router.post("/reset")
    async def reset(request: Request) -> dict[str, Any]:
        body = await _body(request)
        level, remove_key = body.get("level"), body.get("remove_key", False)
        if level not in NAMES:
            raise HTTPException(
                status_code=400, detail=f"Choose a level to reset: {', '.join(NAMES)}."
            )
        if not isinstance(remove_key, bool):
            raise HTTPException(status_code=400, detail="Send remove_key as true or false.")
        return await service.resetter.reset(level, remove_key=remove_key)

    @router.get("/backups")
    async def list_backups() -> dict[str, Any]:
        found = await asyncio.to_thread(backups.list_all, service.config)
        return {"backups": [b.as_dict() for b in found]}

    @router.post("/backups/{backup_id}/restore")
    async def restore(backup_id: str) -> dict[str, Any]:
        try:
            return await service.resetter.restore(backup_id)
        except backups.UnknownBackup as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

    return router


async def _body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if not raw:
        return {}
    try:
        body = json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="The body must be a JSON object.") from None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="The body must be a JSON object.")
    return body


async def _refusable(call: Awaitable[dict[str, Any]]) -> dict[str, Any]:
    try:
        return await call
    except Refused as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
