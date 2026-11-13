"""`Phone`: the channel's lifetime, its settings, and what the settings window asks.

It loads `phone.json`, keeps the transport connected while the channel is on
and a token is stored (the transport reconnects by itself; this only starts
it again after an unexpected failure, with back-off), and stops cleanly with
the daemon. A refused token stops the channel until a new one is stored.

The token goes from the window to the Keychain through `store_token` and is
read back only to connect. `view()` never contains it.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from pathlib import Path
from typing import Any, Literal

from keyring.errors import KeyringError

from vision.core.config import MAX_AWAY_S, MIN_AWAY_S
from vision.core.events import Notice
from vision.remote import audio, store
from vision.remote.channel import PhoneChannel
from vision.remote.ears import Ears
from vision.remote.host import PHONE_NEVER, Host
from vision.remote.link import Link
from vision.remote.pairing import Pairing
from vision.remote.rules import CHOICES, FIELDS, KINDS
from vision.remote.store import PhoneState
from vision.remote.token import TokenStore
from vision.remote.transport import (
    BotIdentity,
    TokenRefused,
    Transport,
    TransportFactory,
    TransportFatal,
    Unreachable,
)

log = logging.getLogger(__name__)

SERVICE = "discord"
TOKEN_SHAPE = re.compile(r"^[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{20,}$")
MAX_RESTART_S = 300.0
SWITCHES = ("enabled", "speak_on_mac", "voice_replies")

Connection = Literal["off", "no_token", "connecting", "online", "offline", "refused"]
Verdict = Literal["accepted", "refused", "unreachable", "none"]


class Refused(ValueError):
    """A request that cannot be done; the message is for people."""


class Phone:
    def __init__(
        self,
        host: Host,
        home: Path,
        *,
        tokens: TokenStore,
        transports: TransportFactory,
        ears: Ears,
        decoders: list[audio.Decoder],
    ) -> None:
        self._host = host
        self._path = store.path_for(home)
        self._tokens = tokens
        self._transports = transports
        self._ears = ears
        self._decoders = decoders
        self.state = PhoneState()
        self.pairing = Pairing()
        self.connection: Connection = "off"
        self.detail: str | None = None
        self._transport: Transport | None = None
        self._link = Link(host, self.pairing, lambda: self.state, self._save, lambda: self._transport)
        self.channel = PhoneChannel(self._link, ears, decoders)
        self._channel_task: asyncio.Task[None] | None = None
        self._connect_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------ lifetime

    async def start(self) -> None:
        self.state = await asyncio.to_thread(store.load, self._path)
        self._channel_task = asyncio.create_task(self.channel.run(), name="phone-channel")
        await self._reconnect()

    async def stop(self) -> None:
        await self.channel.outbox.close()
        await self._disconnect()
        if self._channel_task is not None:
            self._channel_task.cancel()
            await asyncio.gather(self._channel_task, return_exceptions=True)
            self._channel_task = None
        await asyncio.to_thread(self._ears.close)

    async def reload(self) -> None:
        """Read `phone.json` again (after a reset or a restore) and reconnect."""
        async with self._lock:
            self.pairing.clear()
            self.state = await asyncio.to_thread(store.load, self._path)
            await self._reconnect()

    async def _save(self) -> None:
        await asyncio.to_thread(store.save, self._path, self.state)

    async def _disconnect(self) -> None:
        task, self._connect_task = self._connect_task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _reconnect(self) -> None:
        await self._disconnect()
        self.detail = None
        if not self.state.enabled:
            self.connection = "off"
            return
        token = await asyncio.to_thread(self._tokens.get)
        if token is None:
            self.connection = "no_token"
            return
        self.connection = "connecting"
        self._connect_task = asyncio.create_task(self._keep_connected(token), name="phone-connect")

    async def _keep_connected(self, token: str) -> None:
        delay = 1.0
        while True:
            transport = self._transports(token)
            self._transport = transport
            try:
                await transport.listen(self.channel.handlers(self._online))
            except TokenRefused:
                self._stopped("refused", "Discord refused the bot token. Store a new one in Settings, Phone.")
                return
            except TransportFatal as exc:
                self._stopped("refused", str(exc))
                return
            except Exception as exc:
                log.warning("the phone channel stopped (%s); starting it again", type(exc).__name__)
                self.connection = "offline"
            finally:
                self._transport = None
                await transport.close()
            await asyncio.sleep(delay)
            delay = min(MAX_RESTART_S, delay * 2)

    def _online(self, up: bool) -> None:
        self.connection = "online" if up else "offline"

    def _stopped(self, connection: Connection, why: str) -> None:
        self.connection, self.detail = connection, why
        self._host.bus.publish(Notice(level="warn", text=f"The phone channel stopped: {why}"))

    # ------------------------------------------------------------ the window

    async def view(self) -> dict[str, Any]:
        s = self.state
        stored, models, decoder = await asyncio.to_thread(self._disk)
        code = self.pairing.current()
        tools = self._host.tools()
        return {
            "service": SERVICE,
            "enabled": s.enabled,
            "token": {"stored": stored},
            "bot": {"name": s.bot_name or None},
            "connection": self.connection,
            "detail": self.detail,
            "paired": {"name": s.owner_name, "since": s.paired_at} if s.paired else None,
            "pairing": {"code": code.code, "expires_at": code.expires_at} if code else None,
            "notify": {kind: getattr(s, FIELDS[kind]) for kind in KINDS},
            "presence": self._presence(),
            "speak_on_mac": s.speak_on_mac,
            "voice_replies": s.voice_replies,
            "tools": [{"id": t, "title": title} for t, title in tools],
            "phone_tools": [t for t, _ in tools if self._link.phone_may_approve(t)],
            "mac_only": sorted(PHONE_NEVER),
            "voice_notes": {"models": models, "decoder": decoder},
        }

    def _presence(self) -> dict[str, Any]:
        seen = self._host.presence()
        return {
            "away": seen.away,
            "known": seen.known,
            "reason": seen.reason,
            "since": seen.since,
            "away_after_s": self._host.away_after_s(),
        }

    def _disk(self) -> tuple[bool, bool, str | None]:
        found = audio.first_available(self._decoders)
        return self._tokens.get() is not None, self._ears.installed(), found.name if found else None

    async def update(self, body: dict[str, Any]) -> dict[str, Any]:
        """Change switches, what is sent, the away time and the phone's tools. Raises
        `Refused` before changing anything."""
        known = {*SWITCHES, "notify", "phone_tools", "away_after_s"}
        unknown = sorted(set(body) - known)
        if unknown:
            raise Refused(f"There is no phone setting called {unknown[0]!r}.")
        changes: dict[str, Any] = {}
        for key in SWITCHES:
            if key in body:
                changes[key] = _flag(body[key], key)
        if "notify" in body:
            notify = body["notify"]
            if not isinstance(notify, dict) or set(notify) - set(KINDS):
                raise Refused(f"notify takes {', '.join(KINDS)}, each {', '.join(CHOICES)}.")
            for kind, value in notify.items():
                if value not in CHOICES:
                    raise Refused(f"Send {kind} as one of {', '.join(CHOICES)}.")
                changes[FIELDS[kind]] = value
        if "phone_tools" in body:
            changes["phone_tools"] = self._tools(body["phone_tools"])
        away = _away_after(body["away_after_s"]) if "away_after_s" in body else None
        if away is not None and away != self._host.away_after_s():
            await self._host.set_away_after(away)
        async with self._lock:
            reconnect = "enabled" in changes and changes["enabled"] != self.state.enabled
            for key, value in changes.items():
                setattr(self.state, key, value)
            await self._save()
            if reconnect:
                await self._reconnect()
        return await self.view()

    def _tools(self, value: Any) -> list[str]:
        known = [t for t, _ in self._host.tools()]
        if not isinstance(value, list) or not all(isinstance(t, str) for t in value):
            raise Refused("phone_tools is a list of tool ids.")
        never = sorted(set(value) & PHONE_NEVER)
        if never:
            raise Refused(f"{never[0]} is only ever approved at the Mac.")
        strange = sorted(set(value) - set(known))
        if strange:
            raise Refused(f"There is no tool called {strange[0]!r}.")
        return [t for t in known if t in value]

    async def store_token(self, body: dict[str, Any]) -> dict[str, Any]:
        token = body.get("token")
        if not isinstance(token, str) or not TOKEN_SHAPE.match(token.strip()):
            raise Refused(
                "That does not look like a Discord bot token. Copy it again from the Developer "
                "Portal: your application, Bot, Reset Token."
            )
        token = token.strip()
        verdict, identity = await self._check(token)
        if verdict == "refused":
            raise Refused("Discord refused that token, so it was not stored. Reset it in the Developer Portal and try again.")
        try:
            await asyncio.to_thread(self._tokens.put, token)
        except (KeyringError, OSError) as exc:
            raise Refused(f"The Keychain did not store the token ({type(exc).__name__}). Try again.") from None
        async with self._lock:
            if identity is not None:
                if self.state.bot_id and identity.id != self.state.bot_id:
                    self.state.unpair()
                self.state.bot_id, self.state.bot_name = identity.id, identity.name
            await self._save()
            await self._reconnect()
        return {"stored": True, "verdict": verdict, "bot": self.state.bot_name or None}

    async def verify(self) -> dict[str, Any]:
        token = await asyncio.to_thread(self._tokens.get)
        if token is None:
            return {"verdict": "none", "bot": None}
        verdict, identity = await self._check(token)
        if identity is not None and identity.name != self.state.bot_name:
            self.state.bot_name = identity.name
            await self._save()
        return {"verdict": verdict, "bot": self.state.bot_name or None}

    async def _check(self, token: str) -> tuple[Verdict, BotIdentity | None]:
        transport = self._transports(token)
        try:
            return "accepted", await transport.identify()
        except TokenRefused:
            return "refused", None
        except Unreachable:
            return "unreachable", None
        finally:
            await transport.close()

    def new_code(self) -> dict[str, Any]:
        if self.state.paired:
            raise Refused("The phone is already paired. Unpair it first to pair another.")
        code = self.pairing.issue()
        return {"code": code.code, "expires_at": code.expires_at}

    async def unpair(self) -> dict[str, Any]:
        async with self._lock:
            self.pairing.clear()
            self.state.unpair()
            await self._save()
        return await self.view()

    async def send_job_result(self, job_id: str, text: str, *, from_phone: bool, started_at: float) -> None:
        """The host's report of a finished job, sent by its choice (`Notifier.job_result`)."""
        await self.channel.notifier.job_result(job_id, text, from_phone=from_phone, started_at=started_at)

    async def tell_about_proposal(self, key: str, text: str) -> None:
        """An agent's proposal waits at the Mac (`Notifier.proposal`)."""
        await self.channel.notifier.proposal(key, text)

    async def message(self, text: str) -> str:
        """`send_to_phone`: send now, whatever the away state. Answers in words for the model."""
        s = self.state
        if not s.paired:
            return "No phone is paired, so nothing was sent. The owner pairs one in Settings, Phone."
        if not s.enabled:
            return "The phone channel is turned off in Settings, Phone, so nothing was sent."
        if self.connection in ("no_token", "refused"):
            return "The phone channel is not working (no bot token, or Discord refused it), so nothing was sent."
        if s.notify_assistant == "never":
            return "Messages from the assistant to the phone are turned off in Settings, Phone, so nothing was sent."
        sent = await self.channel.outbox.send(f"message:{uuid.uuid4().hex}", text, ping=True)
        if sent == "sent":
            return "Sent to the owner's phone."
        return (
            "Discord could not be reached just now. It will be tried again a few times over the next "
            "minute and a half; if it still fails the owner sees a notice in the app."
        )

    async def forget_token(self) -> None:
        """Remove the token from the Keychain and disconnect (a reset that removes secrets)."""
        await asyncio.to_thread(self._tokens.delete)
        async with self._lock:
            await self._reconnect()


def _away_after(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not MIN_AWAY_S <= value <= MAX_AWAY_S:
        raise Refused(f"The away time is a number of seconds from {MIN_AWAY_S:g} to {MAX_AWAY_S:g}.")
    return float(value)


def _flag(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise Refused(f"Send {name} as true or false.")
    return value
