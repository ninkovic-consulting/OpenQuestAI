"""The section on procedures in an agent's prompt: a resident's system prompt and the host's context."""

from __future__ import annotations

from collections.abc import Mapping

from vision.procedures.store import Procedures

HEADING = "# Your procedures"
INSTRUCTION = (
    "Before you do a kind of work one of these covers, open it with read_procedure and follow it. "
    "After work that went well and is likely to come again, save how you did it with save_procedure, "
    "or improve the one you used. These are your own written notes; saving one needs nobody's yes."
)
NONE_YET = "None yet."


def prompt_part(store: Procedures, agent: str, room_chars: int = 1500, names: Mapping[str, str] | None = None) -> str:
    """The heading, the instruction, then the agent's procedures within `room_chars` (the list's room)."""
    listing = store.listing(agent, room_chars, names)
    return f"{HEADING}\n\n{INSTRUCTION}\n\n{listing or NONE_YET}"
