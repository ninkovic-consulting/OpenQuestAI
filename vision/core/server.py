"""The daemon's HTTP and WebSocket face (spec sections 4.1 and 5).

- Static files from `web/dist` at `/`, or a placeholder page until the web
  app is built.
- `GET /api/health`, `GET /api/state`, `GET /api/history?limit=50`,
  `GET /api/house` (plus the house package's own routes under `/api/house`),
  each needing `Authorization: Bearer <token>`. Other packages protect their
  routers with `require_token`.
- `WS /ws`: the first message must be `hello` with the token, else the
  socket is closed with code 4401. Afterwards the server sends every
  daemon-to-window event and publishes every valid window-to-daemon event on
  the bus.
- Any request or socket with an `Origin` header that is not the server's own
  origin is refused (HTTP 403, WebSocket close 4403).
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import html
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.websockets import WebSocketDisconnect, WebSocketState

from vision import __version__
from vision.core.events import (
    INBOUND_TYPES,
    OUTBOUND_TYPES,
    EventError,
    Hello,
    Notice,
    StateChanged,
    parse_event,
)
from vision.core.token import token_matches

if TYPE_CHECKING:
    from vision.app import Daemon

log = logging.getLogger(__name__)

WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"
HELLO_TIMEOUT_S = 10.0
CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN_ORIGIN = 4403

PLACEHOLDER = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{name}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;
background:#14110f;color:#e8dcc4;font:16px/1.5 system-ui,sans-serif}</style>
</head><body><main><h1>{name} is running</h1>
<p>The Mindspace has not been built yet (<code>web/dist</code> is missing).</p>
</main></body></html>
"""


def allowed_origins(host: str, port: int) -> frozenset[str]:
    """The server's own origins. Built from the bind address, never from `Host`."""
    hosts = {host, "127.0.0.1", "localhost"} if host in ("127.0.0.1", "localhost") else {host}
    return frozenset(f"http://{h}:{port}" for h in hosts)


def require_token(request: Request) -> None:
    """FastAPI dependency: 401 unless `Authorization: Bearer <token>` is correct.

    Reusable by any package: `APIRouter(dependencies=[Depends(require_token)])`.
    The token is read from `request.app.state.token`, set by `create_app`.
    """
    scheme, _, given = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token_matches(request.app.state.token, given.strip()):
        raise HTTPException(status_code=401, detail="missing or wrong token")


def create_app(daemon: Daemon) -> FastAPI:
    origins = allowed_origins(daemon.config.server.host, daemon.port)
    started = time.time()

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await daemon.start()
        try:
            yield
        finally:
            await daemon.stop()

    app = FastAPI(
        title=daemon.config.assistant.name,
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.middleware("http")
    async def check_origin(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        origin = request.headers.get("origin")
        if origin is not None and origin not in origins:
            return JSONResponse({"detail": "forbidden origin"}, status_code=403)
        return await call_next(request)

    app.state.token = daemon.token
    auth = [Depends(require_token)]

    @app.get("/api/health", dependencies=auth)
    async def health() -> dict[str, Any]:
        return {
            "ok": True,
            "version": __version__,
            "brain": daemon.components.brain.name,
            "uptime_s": round(time.time() - started, 1),
        }

    @app.get("/api/state", dependencies=auth)
    async def state() -> dict[str, Any]:
        return {
            **daemon.snapshot.as_dict(),
            "brain": daemon.components.brain.name,
            "budget": dataclasses.asdict(daemon.components.budget.status()),
        }

    @app.get("/api/history", dependencies=auth)
    async def history(limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
        turns = await daemon.components.memory.history(limit)
        return {"turns": [dataclasses.asdict(t) for t in turns]}

    @app.get("/api/house", dependencies=auth)
    async def house() -> dict[str, Any]:
        return daemon.components.house.plan()

    if daemon.components.house.router is not None:
        app.include_router(daemon.components.house.router, prefix="/api/house", dependencies=auth)

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        origin = websocket.headers.get("origin")
        if origin is not None and origin not in origins:
            await websocket.close(code=CLOSE_FORBIDDEN_ORIGIN)
            return
        await websocket.accept()
        if not await _hello(websocket, daemon.token):
            await websocket.close(code=CLOSE_UNAUTHORIZED)
            return
        await _serve_socket(websocket, daemon)

    if WEB_DIST.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
    else:

        @app.get("/", response_class=HTMLResponse)
        async def placeholder() -> str:
            return PLACEHOLDER.replace("{name}", html.escape(daemon.config.assistant.name))

    return app


async def _hello(websocket: WebSocket, token: str) -> bool:
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), HELLO_TIMEOUT_S)
        event = parse_event(raw)
    except (TimeoutError, EventError, WebSocketDisconnect, KeyError, RuntimeError):
        return False
    return isinstance(event, Hello) and token_matches(token, event.token)


async def _serve_socket(websocket: WebSocket, daemon: Daemon) -> None:
    sub = daemon.bus.subscribe(OUTBOUND_TYPES, maxsize=256)

    async def pump() -> None:
        async for event in sub:
            if isinstance(event, StateChanged) and event.brain is None:
                event = event.model_copy(update={"brain": daemon.components.brain.name})
            await websocket.send_text(event.to_json())

    sender = asyncio.create_task(pump())
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                event = parse_event(raw)
            except EventError as exc:
                await websocket.send_text(
                    Notice(level="warn", text=f"Ignored a bad message: {exc}"[:300]).to_json()
                )
                continue
            if event.TYPE in INBOUND_TYPES and not isinstance(event, Hello):
                daemon.bus.publish(event)
            else:
                await websocket.send_text(
                    Notice(level="warn", text=f"Ignored {event.TYPE}: not a window event").to_json()
                )
    except (WebSocketDisconnect, KeyError, RuntimeError):
        pass
    finally:
        sub.close()
        sender.cancel()
        await asyncio.gather(sender, return_exceptions=True)
        if websocket.application_state == WebSocketState.CONNECTED:
            # The window may already be gone; closing a dead socket is not an error.
            with contextlib.suppress(RuntimeError, WebSocketDisconnect):
                await websocket.close()
