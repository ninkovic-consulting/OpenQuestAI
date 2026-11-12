"""A local stand-in for Discord's HTTP API, CDN and Gateway, for tests and live checks.

It speaks the parts the phone channel uses, in Discord's shapes: `GET
/gateway/bot`, `GET /users/@me`, messages (JSON and multipart), edits,
typing, interaction callbacks, attachments, and a Gateway that sends Hello,
answers Identify with READY and Resume with RESUMED, ACKs heartbeats and
closes with 4004 on a wrong token.

Point the daemon at it with `VISION_DISCORD_API=http://127.0.0.1:<port>/api/v10`.
Tests drive it in process (`dm`, `press`, `drop`); a live check drives it
over HTTP:

- `POST /_fake/dm` `{"user_id", "name", "text", "guild_id"?, "voice"?}`
- `POST /_fake/press` `{"user_id", "message_id", "custom_id", "guild_id"?}`
- `GET /_fake/log`: everything the bot did, in order.

    python -m vision.testing.fake_discord --port 8787 --token <test token>
"""

from __future__ import annotations

import argparse
import itertools
import json
from email.parser import BytesParser
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket
from starlette.websockets import WebSocketDisconnect

API = "/api/v10"
BOT = {"id": "900", "username": "vision_bot", "global_name": "Vision Bot", "bot": True}
DM_CHANNEL = "700"


@dataclass
class FakeDiscord:
    token: str
    heartbeat_ms: int = 45_000
    base_url: str = ""
    """`http://127.0.0.1:<port>`, set once the server is up."""
    log: list[dict[str, Any]] = field(default_factory=list)
    files: dict[str, bytes] = field(default_factory=dict)
    sockets: list[WebSocket] = field(default_factory=list)
    identifies: int = 0
    resumes: int = 0
    rate_limit_next: int = 0
    """Answer this many of the next message posts with 429."""
    ack_heartbeats: bool = True
    """False plays a dead connection: heartbeats go unanswered."""
    _ids: itertools.count[int] = field(default_factory=lambda: itertools.count(1000))
    _seq: int = 0
    _sessions: set[str] = field(default_factory=set)

    def next_id(self) -> str:
        return str(next(self._ids))

    def sent(self, kind: str = "message") -> list[dict[str, Any]]:
        return [entry for entry in self.log if entry["kind"] == kind]

    # ------------------------------------------------------------ driving it

    async def dispatch(self, event: str, data: dict[str, Any]) -> None:
        self._seq += 1
        payload = json.dumps({"op": 0, "t": event, "s": self._seq, "d": data})
        for ws in list(self.sockets):
            await ws.send_text(payload)

    async def dm(
        self,
        user_id: str,
        text: str,
        *,
        name: str = "Owner",
        guild_id: str | None = None,
        voice: bytes | None = None,
        bot: bool = False,
    ) -> str:
        message_id = self.next_id()
        data: dict[str, Any] = {
            "id": message_id,
            "type": 0,
            "channel_id": DM_CHANNEL if guild_id is None else "800",
            "author": {"id": user_id, "username": name.lower(), "global_name": name, "bot": bot},
            "content": text,
            "attachments": [],
            "flags": 0,
        }
        if voice is not None:
            self.files[message_id] = voice
            data["flags"] = 1 << 13
            data["attachments"] = [
                {
                    "id": self.next_id(),
                    "filename": "voice-message.ogg",
                    "content_type": "audio/ogg",
                    "size": len(voice),
                    "url": f"{self.base_url}/cdn/{message_id}/voice-message.ogg",
                    "duration_secs": 1.0,
                }
            ]
        if guild_id is not None:
            data["guild_id"] = guild_id
        await self.dispatch("MESSAGE_CREATE", data)
        return message_id

    async def press(self, user_id: str, message_id: str, custom_id: str, *, guild_id: str | None = None) -> str:
        interaction_id = self.next_id()
        data: dict[str, Any] = {
            "id": interaction_id,
            "application_id": BOT["id"],
            "type": 3,
            "token": f"itoken-{interaction_id}",
            "channel_id": DM_CHANNEL,
            "message": {"id": message_id},
            "data": {"custom_id": custom_id, "component_type": 2},
            "context": 1,
        }
        if guild_id is None:
            data["user"] = {"id": user_id, "username": "someone"}
        else:
            data["guild_id"] = guild_id
            data["member"] = {"user": {"id": user_id, "username": "someone"}}
        await self.dispatch("INTERACTION_CREATE", data)
        return interaction_id

    async def drop(self, code: int = 4000) -> None:
        """Close every Gateway connection, as a lost network or Discord would."""
        for ws in list(self.sockets):
            await ws.close(code)

    # ------------------------------------------------------------ the server

    def app(self) -> FastAPI:
        app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

        def authorised(request: Request) -> None:
            if request.headers.get("authorization") != f"Bot {self.token}":
                raise HTTPException(status_code=401, detail={"message": "401: Unauthorized", "code": 0})

        @app.get(f"{API}/gateway/bot")
        async def gateway(request: Request) -> dict[str, Any]:
            authorised(request)
            url = self.base_url.replace("http://", "ws://") + "/gateway"
            limit = {"total": 1000, "remaining": 999, "reset_after": 0, "max_concurrency": 1}
            return {"url": url, "shards": 1, "session_start_limit": limit}

        @app.get(f"{API}/users/@me")
        async def me(request: Request) -> dict[str, Any]:
            authorised(request)
            return BOT

        @app.post(f"{API}/channels/{{channel_id}}/messages")
        async def create(channel_id: str, request: Request) -> Response:
            authorised(request)
            if self.rate_limit_next > 0:
                self.rate_limit_next -= 1
                body = {"message": "You are being rate limited.", "retry_after": 0.05, "global": False}
                return Response(json.dumps(body), status_code=429, media_type="application/json")
            entry = await self._message_body(request)
            message_id = self.next_id()
            self.log.append({"kind": "voice" if "voice" in entry else "message", "channel_id": channel_id, "id": message_id, **entry})
            return Response(json.dumps({"id": message_id, "channel_id": channel_id}), media_type="application/json")

        @app.patch(f"{API}/channels/{{channel_id}}/messages/{{message_id}}")
        async def edit(channel_id: str, message_id: str, request: Request) -> dict[str, Any]:
            authorised(request)
            self.log.append({"kind": "edit", "channel_id": channel_id, "id": message_id, **(await request.json())})
            return {"id": message_id}

        @app.post(f"{API}/channels/{{channel_id}}/typing", status_code=204)
        async def typing(channel_id: str, request: Request) -> Response:
            authorised(request)
            self.log.append({"kind": "typing", "channel_id": channel_id})
            return Response(status_code=204)

        @app.post(f"{API}/interactions/{{interaction_id}}/{{token}}/callback", status_code=204)
        async def callback(interaction_id: str, token: str, request: Request) -> Response:
            if "authorization" in request.headers:
                raise HTTPException(status_code=400, detail="no bot token on interaction callbacks")
            self.log.append({"kind": "ack", "interaction_id": interaction_id, "token": token, **(await request.json())})
            return Response(status_code=204)

        @app.get("/cdn/{message_id}/{name}")
        async def cdn(message_id: str, name: str, request: Request) -> Response:
            if "authorization" in request.headers:
                raise HTTPException(status_code=400, detail="the CDN never gets the bot token")
            data = self.files.get(message_id)
            if data is None:
                raise HTTPException(status_code=404)
            return Response(data, media_type="audio/ogg")

        @app.post("/_fake/dm")
        async def fake_dm(request: Request) -> dict[str, Any]:
            b = await request.json()
            message_id = await self.dm(b["user_id"], b.get("text", ""), name=b.get("name", "Owner"), guild_id=b.get("guild_id"))
            return {"id": message_id}

        @app.post("/_fake/press")
        async def fake_press(request: Request) -> dict[str, Any]:
            b = await request.json()
            return {"id": await self.press(b["user_id"], b["message_id"], b["custom_id"], guild_id=b.get("guild_id"))}

        @app.get("/_fake/log")
        async def fake_log() -> dict[str, Any]:
            return {"log": self.log, "identifies": self.identifies, "resumes": self.resumes}

        @app.websocket("/gateway/")
        @app.websocket("/gateway")
        async def gateway_socket(ws: WebSocket) -> None:
            await ws.accept()
            await ws.send_text(json.dumps({"op": 10, "d": {"heartbeat_interval": self.heartbeat_ms}}))
            try:
                await self._serve_socket(ws)
            except WebSocketDisconnect:
                pass
            finally:
                if ws in self.sockets:
                    self.sockets.remove(ws)

        return app

    async def _message_body(self, request: Request) -> dict[str, Any]:
        kind = request.headers.get("content-type", "")
        if kind.startswith("multipart/form-data"):
            raw = f"Content-Type: {kind}\r\n\r\n".encode() + await request.body()
            parts = {
                part.get_param("name", header="content-disposition"): part.get_payload(decode=True)
                for part in BytesParser().parsebytes(raw).get_payload()
            }
            return {"voice": len(parts["files[0]"]), "payload": json.loads(parts["payload_json"])}
        return dict(await request.json())

    async def _serve_socket(self, ws: WebSocket) -> None:
        while True:
            message = json.loads(await ws.receive_text())
            op, d = message.get("op"), message.get("d")
            if op == 1:
                if self.ack_heartbeats:
                    await ws.send_text(json.dumps({"op": 11}))
            elif op in (2, 6):
                if d.get("token") != self.token:
                    await ws.close(4004)
                    return
                if op == 6 and d.get("session_id") in self._sessions:
                    self.resumes += 1
                    self.sockets.append(ws)
                    self._seq += 1
                    await ws.send_text(json.dumps({"op": 0, "t": "RESUMED", "s": self._seq, "d": {}}))
                    continue
                if op == 6:
                    await ws.send_text(json.dumps({"op": 9, "d": False}))
                    continue
                self.identifies += 1
                session = f"session-{self.next_id()}"
                self._sessions.add(session)
                self.sockets.append(ws)
                self._seq += 1
                ready = {
                    "v": 10,
                    "user": BOT,
                    "session_id": session,
                    "resume_gateway_url": self.base_url.replace("http://", "ws://") + "/gateway",
                    "guilds": [],
                    "application": {"id": BOT["id"]},
                }
                await ws.send_text(json.dumps({"op": 0, "t": "READY", "s": self._seq, "d": ready}))


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="a local fake of Discord for the phone channel")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--token", required=True)
    args = parser.parse_args()
    fake = FakeDiscord(token=args.token, heartbeat_ms=5000, base_url=f"http://127.0.0.1:{args.port}")
    uvicorn.run(fake.app(), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
