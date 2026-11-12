"""What the house can and cannot do today, in one place.

When delegation is built, this is the file to change: wake an agent by adding
its id to `AWAKE`, and set `PROJECT_TOOLS_RUN` once room tools run. The
context summary, the house tools and the status tool all read it from here.
"""

from __future__ import annotations

AWAKE = frozenset({"host"})
"""Agents that can be given work today."""

PROJECT_TOOLS_RUN = False
"""Whether the tools attached to rooms (git, npm and the like) run yet."""


def awake(agent_id: str) -> bool:
    return agent_id in AWAKE


def tool_works(built_in: bool) -> bool:
    """Built-in tools are the assistant's own and run; project tools only once they are switched on."""
    return built_in or PROJECT_TOOLS_RUN


def limits_line() -> str:
    """The plain truth about what can be done today, for the model."""
    return (
        "Today only you are awake. The other agents have their rooms, models and characters, "
        "but they cannot be given work yet and are not doing anything; the tools attached to "
        "rooms are stored but do not run. When asked to delegate, or what another agent is "
        "doing, say so plainly and offer to do what you can yourself; do not pretend and do "
        "not search memory for it."
    )
