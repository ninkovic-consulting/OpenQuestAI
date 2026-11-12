"""Three read-only tools, free tier, behind the gate like every other tool:

- `house_overview`: every room and who runs it, and every agent: role,
  character, model, rooms, state;
- `room_details`: one room, by name or id, said loosely;
- `assistant_status`: the assistant's own setup and status.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from vision.aware.house_view import LIBRARY_ROOM, NoSuchRoom, find_room, overview, room_details
from vision.aware.status import status_text
from vision.core.interfaces import ToolSpec
from vision.gate.tools import Tool, ToolFailure
from vision.memory.library import library_contents

if TYPE_CHECKING:
    from vision.aware import Awareness

NAMES = ("house_overview", "room_details", "assistant_status")

_NO_ARGS: dict[str, Any] = {"type": "object", "properties": {}, "additionalProperties": False}


def build_tools(aware: Awareness) -> list[Tool]:
    """The three tools, in a fixed order (stable for prompt caching)."""

    async def house(args: dict[str, Any]) -> str:
        return overview(aware.view())

    async def room(args: dict[str, Any]) -> str:
        ref = args.get("room")
        if not isinstance(ref, str) or not ref.strip():
            raise ToolFailure("Say which room, by its name or id.")
        view = aware.view()
        try:
            found = find_room(view.plan, ref)
        except NoSuchRoom as exc:
            raise ToolFailure(str(exc)) from None
        library = None
        if found["id"] == LIBRARY_ROOM:
            library = await asyncio.to_thread(library_contents, aware.daemon.config)
        return room_details(view, found, library)

    async def status(args: dict[str, Any]) -> str:
        daemon = aware.daemon
        return status_text(daemon, await daemon.app.state.settings.settings())

    return [
        Tool(
            ToolSpec(
                "house_overview",
                "Describe the house you live in, as it is right now: every room with the agent who runs "
                "it, its light and whether a project folder is attached, and every agent (you and the "
                "other residents) with their role, character, model, rooms and whether they are awake. "
                "Use it whenever the user asks about the house, its rooms, the agents or residents, who "
                "does what, or what is where. Do not search memory for these; this is the source.",
                _NO_ARGS,
            ),
            house,
            "Describe the house",
            "",
            describe=lambda args: "Reads the rooms and agents.",
        ),
        Tool(
            ToolSpec(
                "room_details",
                "Describe one room of the house: the agent who runs it and its model, the project folder, "
                "each tool with whether it is installed and whether it works yet, and the room's light. "
                "For the Library it also lists what the shared library notes contain. Use it whenever the "
                "user asks about a particular room or what is in it. Names are matched loosely "
                "(\"the library\", \"workshop\", \"control-room\").",
                {
                    "type": "object",
                    "properties": {"room": {"type": "string", "description": "The room's name or id, as the user said it."}},
                    "required": ["room"],
                    "additionalProperties": False,
                },
            ),
            room,
            "Describe a room",
            "room",
        ),
        Tool(
            ToolSpec(
                "assistant_status",
                "Your own setup and status: your name, which brain and model is answering now and whether "
                "it is the local fallback, this month's API spend and cap, whether voice is on and the "
                "microphone allowed, the automations and the next one due, whether the phone channel is "
                "connected and paired, which tools ask first, where your data lives, and the app version. "
                "Use it whenever the user asks how you are set up, what model you run on, what has been "
                "spent, or anything about your own state.",
                _NO_ARGS,
            ),
            status,
            "Check its own status",
            "",
            describe=lambda args: "Reads its own settings and status.",
        ),
    ]
