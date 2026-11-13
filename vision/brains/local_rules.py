"""What a local model is always told: it answers without tools.

The local model takes over when Claude cannot be reached. It gets the same
memory and the same summary of the house as Claude does, and those talk about
handing work to residents and using tools. Without this line a small model
plays along and invents a result.
"""

from __future__ import annotations

NO_TOOLS = (
    "You are answering on the small local model because the main model is not available right now. "
    "You have no tools: you cannot hand work to the residents, remember or look anything up, open apps "
    "or links, run commands or change automations, whatever else this conversation says about tools. "
    "If asked for any of that, say plainly that it has to wait until the main model is back, and "
    "never make up a result."
)


def with_rules(core: str) -> str:
    """The system prompt for a local model: the memory core, then the rule."""
    return f"{core.rstrip()}\n\n{NO_TOOLS}" if core.strip() else NO_TOOLS
