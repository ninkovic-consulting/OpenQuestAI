"""Discord's Gateway over a WebSocket (`websockets`), for direct messages only.

The documented life of a connection (API v10, JSON encoding):

1. `GET /gateway/bot` gives the URL; connect with `?v=10&encoding=json`.
2. Hello (op 10) gives `heartbeat_interval`. The first heartbeat (op 1, the
   last sequence number) goes after `interval * random()`, then one every
   interval. A heartbeat without an ACK (op 11) before the next one means the
   connection is dead (a sleeping Mac, a lost network): it is closed with a
   non-1000 code and resumed.
3. Identify (op 2) with the token and the intents, or Resume (op 6) with the
   session id and last sequence on `resume_gateway_url`.
4. Dispatches (op 0) carry the events. Op 1 asks for a heartbeat now, op 7
   asks to reconnect and resume, op 9 says the session is invalid (`d` true:
   resume, false: identify afresh).

Close codes 4004 (bad token) raises `TokenRefused`; 4010 to 4014 raise
`TransportFatal`; any other drop reconnects with exponential back-off and
jitter (1 s doubling to 60 s), resuming when it can. Back-off restarts after
each READY or RESUMED.

Only `DIRECT_MESSAGES` is asked for. In direct messages Discord sends the
message content without the privileged `MESSAGE_CONTENT` intent, and button
presses (`INTERACTION_CREATE`) need no intent.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidURI

from vision.remote.discord.rest import DiscordRest
from vision.remote.transport import TokenRefused, TransportFatal, Unreachable

log = logging.getLogger(__name__)

VERSION = 10
DIRECT_MESSAGES = 1 << 12
INTENTS = DIRECT_MESSAGES
HELLO_TIMEOUT_S = 20.0
MAX_BACKOFF_S = 60.0
ZOMBIE_CLOSE = 4000
FATAL_CLOSES = {
    4010: "Discord says the shard is invalid.",
    4011: "Discord requires sharding for this bot.",
    4012: "Discord no longer accepts this API version.",
    4013: "Discord says the intents are invalid.",
    4014: "Discord refused an intent this bot is not allowed.",
}
FRESH_CLOSES = frozenset({4007, 4009})
"""After these the session cannot be resumed."""

Dispatch = Callable[[str, dict[str, Any]], Awaitable[None]]
Connect = Callable[[str], Any]


def _connect(url: str) -> Any:
    return connect(url, ping_interval=None, max_size=8 * 1024 * 1024, open_timeout=20, close_timeout=5)


class _Reconnect(Exception):
    """Drop this connection and open another; `fresh` forgets the session."""

    def __init__(self, fresh: bool = False) -> None:
        self.fresh = fresh


class Gateway:
    def __init__(
        self,
        token: str,
        rest: DiscordRest,
        dispatch: Dispatch,
        *,
        online: Callable[[bool], None] = lambda up: None,
        connector: Connect = _connect,
        rand: Callable[[], float] = random.random,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._token = token
        self._rest = rest
        self._dispatch = dispatch
        self._online = online
        self._connector = connector
        self._rand = rand
        self._sleep = sleep
        self._url: str | None = None
        self.session_id: str | None = None
        self.resume_url: str | None = None
        self.seq: int | None = None
        self.user: dict[str, Any] = {}
        self.ready = False
        """Set by READY or RESUMED on the connection just closed; resets the back-off."""

    async def run(self) -> None:
        """Stay connected until cancelled. Raises `TokenRefused` or `TransportFatal`."""
        failures = 0
        while True:
            try:
                await self._session()
            except _Reconnect as again:
                if again.fresh:
                    self.session_id = self.resume_url = None
                    self.seq = None
            except ConnectionClosed as closed:
                code = closed.rcvd.code if closed.rcvd is not None else None
                if code == 4004:
                    raise TokenRefused("Discord refused the bot token.") from None
                if code in FATAL_CLOSES:
                    raise TransportFatal(FATAL_CLOSES[code]) from None
                if code in FRESH_CLOSES:
                    self.session_id = self.resume_url = None
                    self.seq = None
                log.info("discord gateway closed (%s); reconnecting", code)
            except (OSError, TimeoutError, InvalidHandshake, InvalidURI, Unreachable, ValueError, KeyError) as exc:
                log.info("discord gateway unreachable (%s); retrying", type(exc).__name__)
            self._online(False)
            if self.ready:
                failures = 0
                self.ready = False
            failures += 1
            delay = min(MAX_BACKOFF_S, 2 ** (failures - 1)) * (0.5 + self._rand() / 2)
            await self._sleep(delay)

    async def _gateway_url(self) -> str:
        if self.session_id and self.resume_url:
            base = self.resume_url
        else:
            if self._url is None:
                answer = await self._rest.call("GET", "/gateway/bot")
                self._url = str(answer["url"])
            base = self._url
        return f"{base.rstrip('/')}/?v={VERSION}&encoding=json"

    async def _session(self) -> None:
        url = await self._gateway_url()
        async with self._connector(url) as ws:
            hello = json.loads(await asyncio.wait_for(ws.recv(), HELLO_TIMEOUT_S))
            if hello.get("op") != 10:
                raise _Reconnect(fresh=False)
            interval = float(hello["d"]["heartbeat_interval"]) / 1000.0
            acked = asyncio.Event()
            acked.set()
            beat = asyncio.create_task(self._heartbeat(ws, interval, acked))
            try:
                await self._send(ws, self._hello_reply())
                await self._receive(ws, acked)
            finally:
                beat.cancel()
                await asyncio.gather(beat, return_exceptions=True)

    def _hello_reply(self) -> dict[str, Any]:
        if self.session_id and self.seq is not None:
            return {"op": 6, "d": {"token": self._token, "session_id": self.session_id, "seq": self.seq}}
        return {
            "op": 2,
            "d": {
                "token": self._token,
                "intents": INTENTS,
                "properties": {"os": "macos", "browser": "vision", "device": "vision"},
            },
        }

    async def _heartbeat(self, ws: ClientConnection, interval: float, acked: asyncio.Event) -> None:
        await asyncio.sleep(interval * self._rand())
        while True:
            if not acked.is_set():
                log.info("discord gateway missed a heartbeat ACK; reconnecting")
                await ws.close(ZOMBIE_CLOSE, "no heartbeat ack")
                return
            acked.clear()
            await self._send(ws, {"op": 1, "d": self.seq})
            await asyncio.sleep(interval)

    async def _receive(self, ws: ClientConnection, acked: asyncio.Event) -> None:
        async for raw in ws:
            payload = json.loads(raw)
            op = payload.get("op")
            if payload.get("s") is not None:
                self.seq = int(payload["s"])
            if op == 0:
                await self._on_dispatch(str(payload.get("t")), payload.get("d") or {})
            elif op == 1:
                await self._send(ws, {"op": 1, "d": self.seq})
            elif op == 11:
                acked.set()
            elif op == 7:
                await ws.close(ZOMBIE_CLOSE, "reconnect requested")
                raise _Reconnect(fresh=False)
            elif op == 9:
                await self._sleep(1 + 4 * self._rand())
                await ws.close(ZOMBIE_CLOSE, "invalid session")
                raise _Reconnect(fresh=not payload.get("d"))
        raise _Reconnect(fresh=False)

    async def _on_dispatch(self, event: str, data: dict[str, Any]) -> None:
        if event == "READY":
            self.session_id = str(data["session_id"])
            self.resume_url = str(data["resume_gateway_url"])
            self.user = dict(data.get("user") or {})
            self.ready = True
            self._online(True)
        elif event == "RESUMED":
            self.ready = True
            self._online(True)
        else:
            await self._dispatch(event, data)

    @staticmethod
    async def _send(ws: ClientConnection, payload: dict[str, Any]) -> None:
        await ws.send(json.dumps(payload, separators=(",", ":")))
