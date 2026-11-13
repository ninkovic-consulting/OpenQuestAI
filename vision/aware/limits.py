"""What the house can and cannot do in this build, in one place.

Every resident (each agent but the host) can take work through `hand_off`.
In offline mode everyone runs on the local model (`offline_line`).
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
    workbench is installed (and the room has a project folder that can be used)."""
    return built_in or project_tools


def can_do(agent_id: str) -> str:
    """One resident's abilities at work, in a sentence."""
    extra = [abilities.WORDS[t] for t in abilities.extra(agent_id) if t in abilities.WORDS]
    said = (
        "keeps its own notes and procedures, can propose a new tool or a change to its own persona, model "
        "or thinking level (the owner decides at the Mac), can ask another resident for help through the board"
    )
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
        "running the room's programs) work in a room's project folders."
        if project_tools
        else "Project tools are not installed in this build, so residents cannot read or change project "
        "files or run programs."
    )
    return (
        "The residents can take work: hand it off with hand_off and a complete brief, and you are "
        "told the result later in a turn of its own. When the owner asks to look at, check, read or "
        "research a website, a link or anything that needs the web, hand it to the scout at once (it "
        "loads pages itself) and say it is under way; hand tests and reviews to the checker and code "
        "to the maker the same way. Do not ask whether to and do not offer it as an option. A resident can work in any room but the Hall: "
        "send it to the room whose project the work is about (the checker to the Workshop to test "
        f"the maker's project, say). {tools} Only you open apps and links, run the "
        "shell, change automations, hand out work and start projects; residents never talk to the owner, and the "
        "envoy cannot send or read mail or messages yet. Say so plainly when asked for something "
        "nobody here can do; do not pretend."
    )


def projects_line() -> str:
    """That the host can start a new project, and how it chooses who gets it, for the model."""
    return (
        "When the owner asks you to start a new project, use start_project: it makes the project's "
        "folder (or attaches an existing one), adds a room for it run by the resident you choose, and can "
        "give that resident a first job, once the owner says yes to exactly that. Choose the maker for "
        "software, the scout for research, the envoy for writing and communication and the steward for "
        "upkeep of this Mac and the house (the checker reviews rather than owns), follow the owner when "
        "they name an agent, and say why."
    )


def learning_line() -> str:
    """What every agent can now do for itself, and the line nobody crosses, for the model."""
    return (
        "Every agent, you included, keeps written procedures: open one with read_procedure before work it "
        "covers, and save or improve one with save_procedure after work that went well; that needs nobody's "
        "yes. An agent may also propose a new tool (a small script) with propose_tool, or a change to its own "
        "persona, model or thinking level with propose_change; you may propose one for a resident too. A "
        "proposal does nothing until the owner approves it in the window at the Mac: a yes in the "
        "conversation, by voice or from the phone does not approve it, so tell the owner it waits in "
        "Proposals. Tools named made_... were written by an agent and approved by the owner; they run "
        "confined by macOS to the folders and network the owner allowed, asking first unless the owner made "
        "them free. Nobody can change the approval rules, their own permissions, spending caps, keys, the "
        "phone's approval list or the assistant's own code. When something is refused or nobody answers, try "
        "another approach, ask a resident or say what blocked it, but never look for another route to the "
        "same thing."
    )


def offline_line(model: str, tools: bool | None) -> str:
    """The truth of offline mode, for the model: what runs where and what does not work."""
    said = (
        f"Offline mode is on: you and the residents run on the local model {model} on this Mac, and "
        "nothing is sent to Anthropic. Web search and loading web pages are not available, so the scout "
        "cannot search the web or read a site."
    )
    if tools is False:
        said += (
            " This model cannot use tools: you cannot hand off work, remember, look anything up or "
            "open anything, and must say so plainly when asked."
        )
    return said
