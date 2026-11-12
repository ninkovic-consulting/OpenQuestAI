"""The phone channel over Discord: a bot that serves direct messages only.

Receiving is the Gateway (`gateway.py`); everything else is the HTTP API
(`rest.py`):

- a message: `POST /channels/{id}/messages`, at most 2,000 characters, so a
  long reply is split (`vision.remote.text`) after escaping (`markdown.py`);
  mentions are disarmed;
- buttons: one action row with a green Yes and a grey Not now (button styles
  3 and 2), each with a `custom_id`;
- a press arrives as `INTERACTION_CREATE` (type 3, a message component) and
  must be answered within three seconds: callback type 7 replaces the
  message and removes its buttons, type 6 changes nothing visible;
- typing: `POST /channels/{id}/typing`, shown for ten seconds;
- a voice note from the mobile app is a message with the voice-message flag
  (`1 << 13`) and one `audio/ogg` attachment, fetched from Discord's CDN
  without the bot token;
- a voice reply is a message with that flag and one Ogg Opus file, with
  `duration_secs` and a base64 `waveform` (multipart, `payload_json` and
  `files[0]`).

Messages from servers (`guild_id` present) and from bots are dropped here.
Events are handed to the channel one at a time in arrival order, off the
Gateway's receive loop, so a slow handler never delays a heartbeat; presses
are handled at once in their own task, because of the three-second deadline.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any
from urllib.parse import urlsplit

import httpx

from vision.remote.discord.gateway import Gateway
from vision.remote.discord.markdown import MAX_CONTENT, escape, escaped_length
from vision.remote.discord.rest import API_BASE, DiscordRest
from vision.remote.text import split_text
from vision.remote.transport import (
    Attachment,
    BotIdentity,
    Button,
    Handlers,
    Incoming,
    Press,
    Unreachable,
)

log = logging.getLogger(__name__)

VOICE_FLAG = 1 << 13
COMPONENT = 3
UPDATE_MESSAGE = 7
DEFERRED_UPDATE = 6
STYLE = {"yes": 3, "no": 2}
NO_MENTIONS = {"parse": []}
CDN_HOSTS = frozenset({"cdn.discordapp.com", "media.discordapp.net"})


class DiscordTransport:
    def __init__(self, token: str, *, base: str = API_BASE, client: httpx.AsyncClient | None = None) -> None:
        self._token = token
        self._rest = DiscordRest(token, base=base, client=client)
        self._cdn_hosts = CDN_HOSTS if base == API_BASE else CDN_HOSTS | {urlsplit(base).hostname or ""}
        self._tasks: set[asyncio.Task[None]] = set()

    @property
    def max_text(self) -> int:
        return MAX_CONTENT

    async def identify(self) -> BotIdentity:
        me = await self._rest.call("GET", "/users/@me")
        return BotIdentity(str(me["id"]), str(me.get("global_name") or me["username"]))

    async def listen(self, handlers: Handlers) -> None:
        events: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()

        async def dispatch(event: str, data: dict[str, Any]) -> None:
            if event == "INTERACTION_CREATE":
                self._spawn(self._on_press(data, handlers))
            elif event == "MESSAGE_CREATE":
                events.put_nowait((event, data))

        async def consume() -> None:
            while True:
                _, data = await events.get()
                message = incoming(data)
                if message is None:
                    continue
                try:
                    await handlers.message(message)
                except Exception:
                    log.exception("the phone channel failed on a message")

        gateway = Gateway(self._token, self._rest, dispatch, online=handlers.online)
        consumer = asyncio.create_task(consume())
        try:
            await gateway.run()
        finally:
            consumer.cancel()
            await asyncio.gather(consumer, return_exceptions=True)

    async def _on_press(self, data: dict[str, Any], handlers: Handlers) -> None:
        press = pressed(data)
        if press is None:
            return
        try:
            await handlers.press(press)
        except Exception:
            log.exception("the phone channel failed on a button press")

    def _spawn(self, work: Any) -> None:
        task = asyncio.create_task(work)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # ------------------------------------------------------------ sending

    async def send(self, chat_id: str, text: str) -> str:
        last = ""
        for piece in split_text(text, MAX_CONTENT, escaped_length):
            last = await self._post(chat_id, {"content": escape(piece)})
        return last

    async def send_buttons(self, chat_id: str, text: str, buttons: list[Button]) -> str:
        row = [
            {"type": 2, "style": STYLE[b.kind], "label": b.label, "custom_id": b.data}
            for b in buttons
        ]
        content = escape(text)[:MAX_CONTENT]
        return await self._post(chat_id, {"content": content, "components": [{"type": 1, "components": row}]})

    async def _post(self, chat_id: str, body: dict[str, Any]) -> str:
        answer = await self._rest.call(
            "POST", f"/channels/{chat_id}/messages", json={**body, "allowed_mentions": NO_MENTIONS}
        )
        return str(answer["id"])

    async def edit(self, chat_id: str, message_id: str, text: str) -> None:
        await self._rest.call(
            "PATCH",
            f"/channels/{chat_id}/messages/{message_id}",
            json={"content": escape(text)[:MAX_CONTENT], "components": [], "allowed_mentions": NO_MENTIONS},
        )

    async def acknowledge(self, press: Press, text: str | None) -> None:
        if text is None:
            body: dict[str, Any] = {"type": DEFERRED_UPDATE}
        else:
            body = {
                "type": UPDATE_MESSAGE,
                "data": {"content": escape(text)[:MAX_CONTENT], "components": [], "allowed_mentions": NO_MENTIONS},
            }
        await self._rest.call("POST", f"/interactions/{press.press_id}/{press.ack_token}/callback", json=body, auth=False)

    async def typing(self, chat_id: str) -> None:
        await self._rest.call("POST", f"/channels/{chat_id}/typing")

    async def fetch(self, attachment: Attachment, limit: int) -> bytes:
        if urlsplit(attachment.url).hostname not in self._cdn_hosts:
            raise Unreachable("The attachment is not on Discord's servers.")
        return await self._rest.download(attachment.url, limit)

    async def send_voice(self, chat_id: str, ogg: bytes, duration_s: float, waveform: bytes) -> str:
        payload = {
            "flags": VOICE_FLAG,
            "allowed_mentions": NO_MENTIONS,
            "attachments": [
                {
                    "id": 0,
                    "filename": "voice-message.ogg",
                    "duration_secs": round(duration_s, 2),
                    "waveform": base64.b64encode(waveform).decode("ascii"),
                }
            ],
        }
        answer = await self._rest.call(
            "POST",
            f"/channels/{chat_id}/messages",
            data={"payload_json": json.dumps(payload)},
            files={"files[0]": ("voice-message.ogg", ogg, "audio/ogg")},
        )
        return str(answer["id"])

    async def close(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self._rest.close()


# ---------------------------------------------------------------- reading events


def _user(data: dict[str, Any]) -> dict[str, Any]:
    return dict(data.get("user") or (data.get("member") or {}).get("user") or data.get("author") or {})


def _name(user: dict[str, Any]) -> str:
    return str(user.get("global_name") or user.get("username") or user.get("id") or "someone")


def incoming(data: dict[str, Any]) -> Incoming | None:
    """A `MESSAGE_CREATE` as the channel sees it; None for bots and system messages."""
    author = _user(data)
    if not author or author.get("bot") or data.get("type", 0) not in (0, 19):
        return None
    voice_message = bool(int(data.get("flags") or 0) & VOICE_FLAG)
    attachments = tuple(
        Attachment(
            url=str(a.get("url", "")),
            filename=str(a.get("filename", "")),
            content_type=str(a.get("content_type") or ""),
            size=int(a.get("size") or 0),
            voice=voice_message,
        )
        for a in data.get("attachments") or []
    )
    return Incoming(
        message_id=str(data.get("id", "")),
        chat_id=str(data.get("channel_id", "")),
        user_id=str(author.get("id", "")),
        user_name=_name(author),
        direct="guild_id" not in data,
        text=str(data.get("content") or ""),
        attachments=attachments,
    )


def pressed(data: dict[str, Any]) -> Press | None:
    """A button press from `INTERACTION_CREATE`; None for any other interaction."""
    if data.get("type") != COMPONENT:
        return None
    user = _user(data)
    message = data.get("message") or {}
    return Press(
        press_id=str(data.get("id", "")),
        ack_token=str(data.get("token", "")),
        chat_id=str(data.get("channel_id", "")),
        message_id=str(message.get("id", "")),
        user_id=str(user.get("id", "")),
        user_name=_name(user),
        direct="guild_id" not in data,
        data=str((data.get("data") or {}).get("custom_id", "")),
    )
