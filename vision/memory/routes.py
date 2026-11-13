"""The library's and the profile's routes, mounted under `/api` behind the token.

- `GET /library`: `{documents, folder, limits}`, documents newest first.
- `POST /library/files`: the file itself as the body, its name in the
  `X-File-Name` header (URL-encoded); the text is taken out now and the file
  kept. Answers `{document}`.
- `POST /library/text`: `{title, text}`, a pasted document. Answers `{document}`.
- `GET /library/documents/{name}`: `{document, text}`.
- `PATCH /library/documents/{name}`: `{title}`, a rename. Answers `{document}`.
- `DELETE /library/documents/{name}`: answers `{removed}`. The window asks first.
- `GET /profile` and `PATCH /profile` (`{name?, business?, notes?}`, only the
  parts given change): answer `{profile}`. Settings carries the same as `owner`.

A refusal is a 400 with a line for people; an unknown document a 404.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Request

from vision.core.server import require_token
from vision.memory import profile
from vision.memory.documents import MAX_DOCUMENTS, TITLE_MAX, Library, LibraryError, NoSuchDocument
from vision.memory.extract import KINDS, MAX_FILE_BYTES, MAX_TEXT_CHARS

FILE_NAME_MAX = 255


def build_router(vault_root: Path) -> APIRouter:
    router = APIRouter(dependencies=[Depends(require_token)])
    library = Library(vault_root)

    async def run(call: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return await asyncio.to_thread(call, *args, **kwargs)
        except NoSuchDocument as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except (LibraryError, profile.BadProfile) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    @router.get("/library")
    async def listing() -> dict[str, Any]:
        docs = await run(library.list)
        return {
            "documents": [d.as_dict() for d in docs],
            "folder": str(library.folder),
            "limits": {
                "max_file_bytes": MAX_FILE_BYTES,
                "max_text_chars": MAX_TEXT_CHARS,
                "max_documents": MAX_DOCUMENTS,
                "title_max": TITLE_MAX,
                "endings": sorted(KINDS),
            },
        }

    @router.post("/library/files")
    async def add_file(request: Request) -> dict[str, Any]:
        name = unquote(request.headers.get("x-file-name", "")).strip()
        if not name or len(name) > FILE_NAME_MAX or "/" in name or any(ord(c) < 32 for c in name):
            raise HTTPException(status_code=400, detail="Send the file's name in the X-File-Name header.")
        declared = request.headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > MAX_FILE_BYTES:
            raise HTTPException(status_code=400, detail=_too_big())
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > MAX_FILE_BYTES:
                raise HTTPException(status_code=400, detail=_too_big())
        doc = await run(library.add_file, name, bytes(data))
        return {"document": doc.as_dict()}

    @router.post("/library/text")
    async def add_text(request: Request) -> dict[str, Any]:
        body = await _body(request)
        doc = await run(library.add_text, body.get("title"), body.get("text"))
        return {"document": doc.as_dict()}

    @router.get("/library/documents/{name:path}")
    async def read(name: str) -> dict[str, Any]:
        doc = await run(library.find_exact, name)
        _, text = await run(library.text, doc.name)
        return {"document": doc.as_dict(), "text": text}

    @router.patch("/library/documents/{name:path}")
    async def rename(name: str, request: Request) -> dict[str, Any]:
        body = await _body(request)
        doc = await run(library.find_exact, name)
        renamed = await run(library.update, doc.name, title=body.get("title", ""))
        return {"document": renamed.as_dict()}

    @router.delete("/library/documents/{name:path}")
    async def remove(name: str) -> dict[str, Any]:
        doc = await run(library.find_exact, name)
        removed = await run(library.remove, doc.name)
        return {"removed": removed.as_dict()}

    @router.get("/profile")
    async def get_profile() -> dict[str, Any]:
        got = await asyncio.to_thread(profile.read, vault_root)
        return {"profile": got.as_dict()}

    @router.patch("/profile")
    async def patch_profile(request: Request) -> dict[str, Any]:
        body = await _body(request)
        stored = await run(profile.update, vault_root, body)
        return {"profile": stored.as_dict()}

    return router


def _too_big() -> str:
    return f"The file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB, the most the library takes."


async def _body(request: Request) -> dict[str, Any]:
    try:
        body = json.loads(await request.body() or b"{}")
    except ValueError:
        raise HTTPException(status_code=400, detail="The body must be a JSON object.") from None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="The body must be a JSON object.")
    return body
