"""`send_to_phone(text)`: the host messages the paired phone on purpose.

Free, and the host's only: it is not in the residents' catalog and not lent
to them. It sends now, whatever the away state, unless messages from the
assistant are set to never, and answers plainly when nothing could be sent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from vision.core.interfaces import ToolSpec
from vision.gate.tools import Tool, ToolFailure
from vision.remote.outbox import REPLY_ROOM

if TYPE_CHECKING:
    from vision.remote.service import Phone

NAME = "send_to_phone"


def build_tools(phone: Phone) -> list[Tool]:
    async def send(args: dict[str, Any]) -> str:
        text = args.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ToolFailure("Say what to send.")
        if len(text.strip()) > REPLY_ROOM:
            raise ToolFailure(f"That is too long for one message; keep it under {REPLY_ROOM} characters.")
        return await phone.message(text)

    return [
        Tool(
            ToolSpec(
                NAME,
                "Send a short message to the owner's paired phone (Discord) now, whether or not they are "
                "at the Mac. Use it when the owner asks for something to be sent to their phone (\"send "
                "that to my phone\", \"text me the address\"), and in an automation whose instruction says "
                "to ping, message or notify the owner. Write the message itself, complete on its own. "
                "Do not use it otherwise: replies to messages from the phone already go back there, and "
                "job results, automation results, warnings and requests for a yes reach the phone by "
                "the owner's settings, so sending them again would arrive twice. It answers whether "
                "the message went, and says so plainly when no phone is paired or the channel is off.",
                {
                    "type": "object",
                    "properties": {"text": {"type": "string", "description": "The message, as the owner should read it."}},
                    "required": ["text"],
                    "additionalProperties": False,
                },
            ),
            send,
            "Send a message to your phone",
            "text",
        )
    ]
