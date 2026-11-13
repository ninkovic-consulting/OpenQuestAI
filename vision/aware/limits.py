"""What the house can and cannot do in this build, in one place.

Every resident (each agent but the host) can take work through `hand_off`.
What each may use at work is `vision.residents.abilities`; this file turns
that into the plain words the host is told, so the context summary, the
house tools and the status tool say the same thing.
"""

from __future__ import annotations

from vision.residents import abilities

HOST = "host"


def can_take_work(agent_id: str) -> bool:
    """Residents take work; the host hands it out and runs no other room."""
    return agent_id != HOST


def tool_works(built_in: bool, project_tools: bool) -> bool:
    """Built-in tools run; a room's project tools run in its resident's jobs when the
    workbench is installed (and the room has a project folder)."""
    return built_in or project_tools


def can_do(agent_id: str) -> str:
    """One resident's abilities at work, in a sentence."""
    extra = [abilities.WORDS[t] for t in abilities.extra(agent_id) if t in abilities.WORDS]
    said = "keeps its own notes, can ask another resident for help through the board"
    if extra:
        said += ", " + ", ".join(extra)
    said += (
        ", and works with the project tools of whichever room it is sent to (any room but the Hall) "
        "when that room has a project folder"
    )
    cannot = abilities.CANNOT_YET.get(agent_id)
    return said + (f"; it {cannot}" if cannot else "")


def limits_line(project_tools: bool) -> str:
    """The plain truth about what can be done today, for the model."""
    tools = (
        "Project tools (reading and searching files, and, after the owner's yes, writing files and "
        "running the room's programs) work in a room's project folder."
        if project_tools
        else "Project tools are not installed in this build, so residents cannot read or change project "
        "files or run programs."
    )
    return (
        "The residents can take work: hand it off with hand_off and a complete brief, and you are "
        "told the result later in a turn of its own. A resident can work in any room but the Hall: "
        "send it to the room whose project the work is about (the checker to the Workshop to test "
        f"the maker's project, say). {tools} Only you open apps and links, run the "
        "shell, change automations and hand out work; residents never talk to the owner, and the "
        "envoy cannot send or read mail or messages yet. Say so plainly when asked for something "
        "nobody here can do; do not pretend."
    )
