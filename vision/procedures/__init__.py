"""Procedures: each agent's written "how I did this", reused and improved.

The host and every resident keep named procedures: steps for a kind of work
that went well and will come again, with a line on when to use them. An agent
opens one before doing work it covers and saves or improves one afterwards,
so the house gets better at its recurring work without anyone retraining it.
They are written notes, never actions, so saving one needs nobody's yes; the
owner reads, edits and removes them in the window.

Where they are (plain Markdown in the vault, `config.paths.house`, which a
person may edit by hand; the format is in `store.py`):

    agents/<agent>/procedures/<name>.md   an agent's own
    procedures/<name>.md                  shared: every agent sees them

The sharing rule: an agent saves and removes its own freely and may share one
(which moves its own copy to the shared folder). A shared one can be changed or
removed only by the agent that wrote it or the host; the owner may change any.
An agent's own procedure with the same name as a shared one takes its place for
that agent.

`Procedures` is the store, `build_tools` an agent's four tools and
`prompt_part` the section of its prompt that lists them. The owner's routes are
`vision.procedures.routes`: they need the core's token check, and the core
imports packages like this one, so they are not imported here.
"""

from __future__ import annotations

from vision.procedures.store import NoSuchProcedure, ProcedureError, Procedures
from vision.procedures.tools import build_tools
from vision.procedures.words import prompt_part

__all__ = ["NoSuchProcedure", "ProcedureError", "Procedures", "build_tools", "prompt_part"]
