"""What each resident may use at work, in one place.

Every resident gets its own notes (`remember`, `recall`), `note_progress`
and `ask_resident` (not in a request from another resident), and the
project tools of its room when the room has a project folder. Some get more
(`EXTRA`). No resident ever gets a tool in `HOST_ONLY`: opening apps and
links, the shell, changing automations and handing out work stay with the
host. `vision.aware.limits` reads this to tell the host the truth.
"""

from __future__ import annotations

STEWARD = "steward"
SCOUT = "scout"
ENVOY = "envoy"

BASE = ("remember", "recall", "note_progress", "ask_resident")
EXTRA: dict[str, tuple[str, ...]] = {
    STEWARD: ("machine_status", "assistant_status", "list_automations"),
    SCOUT: ("web_search", "web_fetch"),
}
"""Tools some residents have beyond the base set, by agent id."""

HOST_ONLY = frozenset(
    {
        "shell",
        "open_app",
        "open_url",
        "create_automation",
        "update_automation",
        "pause_automation",
        "resume_automation",
        "run_automation",
        "delete_automation",
        "hand_off",
        "list_jobs",
        "job_details",
        "cancel_job",
    }
)

CANNOT_YET: dict[str, str] = {
    ENVOY: "has no mail or messaging access yet, so it can draft words but cannot send or read messages",
}
"""Plain words for what an agent's role suggests but this build does not give it."""

WORDS: dict[str, str] = {
    "machine_status": "reads this Mac's disk, memory, battery, uptime and load",
    "assistant_status": "reads the assistant's own setup",
    "list_automations": "lists the automations",
    "web_search": "searches the web",
    "web_fetch": "loads a web page it is given and reads it",
}


def extra(agent: str) -> tuple[str, ...]:
    return EXTRA.get(agent, ())
