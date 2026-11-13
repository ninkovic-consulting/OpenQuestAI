"""The images' routes, mounted under `/api` behind the token.

- `GET /images/limits`: `{limits}` (types, `max_bytes`, `max_pixels`,
  `max_per_message`, `long_edge`).
- `POST /images`: the image itself as the whole body. Its type is read from
  the bytes; the name and `Content-Type` are ignored. Answers `{image: {id,
  media_type, width, height, bytes}}` for the clean copy that is kept.
- `GET /images/{id}`: the kept file, for the owner's own window only (the
  token travels in a header, so the window fetches it and shows a blob).
- `DELETE /images/{id}`: answers `{removed: true}`.

A refusal is a 400 with one plain sentence; an unknown id a 404. The file is
served with `nosniff` and a sandboxing content policy, so even a browser
that opened it directly would only ever show it as an image.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from vision.attachments.clean import MAX_BYTES, TOO_BIG, ImageRefused, limits
from vision.attachments.store import ImageStore, NoSuchImage
from vision.core.server import require_token

SERVED_HEADERS = {
    "Cache-Control": "private, max-age=31536000, immutable",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; sandbox",
    "Content-Disposition": "inline",
}


def build_router(store: ImageStore) -> APIRouter:
    router = APIRouter(dependencies=[Depends(require_token)])

    @router.get("/images/limits")
    async def image_limits() -> dict[str, Any]:
        return {"limits": limits()}

    @router.post("/images")
    async def add(request: Request) -> dict[str, Any]:
        declared = request.headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > MAX_BYTES:
            raise HTTPException(status_code=400, detail=TOO_BIG)
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > MAX_BYTES:
                raise HTTPException(status_code=400, detail=TOO_BIG)
        try:
            picture = await asyncio.to_thread(store.add, bytes(data))
        except ImageRefused as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        return {
            "image": {
                "id": picture.id,
                "media_type": picture.media_type,
                "width": picture.width,
                "height": picture.height,
                "bytes": len(picture.data),
            }
        }

    @router.get("/images/{image_id}")
    async def get(image_id: str) -> Response:
        try:
            data, media_type = await asyncio.to_thread(store.raw, image_id)
        except NoSuchImage:
            raise HTTPException(status_code=404, detail="No such image.") from None
        return Response(content=data, media_type=media_type, headers=SERVED_HEADERS)

    @router.delete("/images/{image_id}")
    async def remove(image_id: str) -> dict[str, Any]:
        try:
            await asyncio.to_thread(store.remove, image_id)
        except NoSuchImage:
            raise HTTPException(status_code=404, detail="No such image.") from None
        return {"removed": True}

    return router
