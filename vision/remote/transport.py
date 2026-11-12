"""The seam between the phone channel and one chat service.

Everything above this interface (pairing, commands, turns, notifications,
approvals) knows nothing about the service. A transport only moves messages:
it receives direct messages and button presses, sends plain text (escaping
and splitting it the way its service needs), sends a message with buttons,
edits one, shows typing, and fetches an attachment.

`vision.remote.discord.DiscordTransport` is the one implementation.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol


class TokenRefused(Exception):
    """The service refused the bot token. Retrying with the same token cannot help."""


class Unreachable(Exception):
    """The service could not be reached, or answered with an error. The text is for people."""


class TransportFatal(Exception):
    """The service will not serve this bot as configured. The text is for people."""


@dataclass(frozen=True, slots=True)
class BotIdentity:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class Attachment:
    url: str
    filename: str
    content_type: str
    size: int
    voice: bool
    """A voice message recorded in the app, rather than any file."""


@dataclass(frozen=True, slots=True)
class Incoming:
    """A message someone sent the bot."""

    message_id: str
    chat_id: str
    user_id: str
    user_name: str
    direct: bool
    """True for a direct message to the bot; False anywhere else (a server)."""
    text: str
    attachments: tuple[Attachment, ...] = ()


@dataclass(frozen=True, slots=True)
class Press:
    """Someone pressed a button on one of the bot's messages."""

    press_id: str
    ack_token: str
    """Opaque: what the transport needs to acknowledge this press."""
    chat_id: str
    message_id: str
    user_id: str
    user_name: str
    direct: bool
    data: str


@dataclass(frozen=True, slots=True)
class Button:
    data: str
    label: str
    kind: Literal["yes", "no"]


@dataclass(frozen=True, slots=True)
class Handlers:
    """What the transport calls while it listens. Each must return quickly."""

    message: Callable[[Incoming], Awaitable[None]]
    press: Callable[[Press], Awaitable[None]]
    online: Callable[[bool], None] = field(default=lambda up: None)
    """Hears the connection come up (True) and drop (False)."""


class Transport(Protocol):
    async def identify(self) -> BotIdentity:
        """Who the token belongs to. Raises `TokenRefused` or `Unreachable`."""
        ...

    async def listen(self, handlers: Handlers) -> None:
        """Receive until cancelled, reconnecting by itself with back-off.

        Raises `TokenRefused` when the token is refused and `TransportFatal`
        when the service will not serve the bot as configured.
        """
        ...

    async def send(self, chat_id: str, text: str) -> str:
        """Send plain text, split into as many messages as it needs; the last one's id."""
        ...

    async def send_buttons(self, chat_id: str, text: str, buttons: list[Button]) -> str:
        """One message with buttons under it. `text` must fit one message."""
        ...

    async def edit(self, chat_id: str, message_id: str, text: str) -> None:
        """Replace a message's text and remove its buttons."""
        ...

    async def acknowledge(self, press: Press, text: str | None) -> None:
        """Answer a press at once: with `text`, the pressed message becomes it, without
        buttons; with None, nothing visible changes."""
        ...

    async def typing(self, chat_id: str) -> None:
        """Show that a reply is being written, for a few seconds."""
        ...

    async def fetch(self, attachment: Attachment, limit: int) -> bytes:
        """Download an attachment, at most `limit` bytes. Raises `Unreachable`."""
        ...

    async def send_voice(self, chat_id: str, ogg: bytes, duration_s: float, waveform: bytes) -> str:
        """Send an Ogg Opus voice message. Raises `Unreachable` when it is refused."""
        ...

    @property
    def max_text(self) -> int:
        """The most characters one message may hold."""
        ...

    async def close(self) -> None: ...


TransportFactory = Callable[[str], Transport]
"""Builds a transport for a bot token."""
