"""Proposals: agents that extend themselves, only with the owner's yes at the Mac.

An agent may do two things it cannot do alone, and only by asking:

- write a small script as a new tool (`propose_tool`). It does nothing until
  the owner reads the code on a card and approves it. After that it is
  `made_<name>`, a gate tool that runs confined by macOS (`sandbox`), timed
  and audited, asking each time unless the owner set it to run freely;
- propose a change to its own persona, model or thinking level
  (`propose_change`), which the owner sees as before and after. The host may
  propose one for a resident too.

The hard line: approval happens at the Mac only, in the window, through the
owner's routes (`routes`). No agent tool, gate request, phone button or spoken
or typed yes can approve, decline or put back a proposal; nothing here listens
to `gate.decision` or reads yes or no from text. An agent whose proposal or
tool call is refused may try another approach, ask another agent or report
what blocked it, but never looks for another route to the same thing. And no
proposal can touch the approval rules, permissions, spending caps, keys, the
phone's approval list or the app's own code: only the three fields above can
be proposed, which is checked in code (`changes`).

Where things are kept (in `$VISION_HOME`):

    proposals.json                     every waiting proposal, the newest 200 decided
    made-tools/<name>/manifest.json    the owner's choices and each version's pinned sha256
    made-tools/<name>/versions/<n>.py  the exact text approved (or .sh)
    made-tools/<name>/runs.json        the newest 50 runs
    made-tools/scratch/<run id>/       one run's folder, removed after it

What approving means: for a tool, the script as shown is written as a new
version whose hash is pinned, and the tool is turned on for its author (or
every agent) at the tier chosen; before each run the file is hashed again and
a mismatch turns the tool off. For a change, the value is applied through the
normal settings validation (or written to the persona file); a refusal leaves
the proposal waiting. Every decision is written to the audit log.

`Proposals` (`service`) ties it together; `routes.build_router` needs the
core's token check, and the core imports packages like this one, so the
routes are not imported here.
"""

from __future__ import annotations

from vision.proposals.changes import ALLOWED_FIELDS
from vision.proposals.model import (
    PER_AGENT,
    TOTAL,
    Context,
    NotFound,
    Proposal,
    ProposalError,
)
from vision.proposals.service import Proposals

__all__ = ["ALLOWED_FIELDS", "PER_AGENT", "TOTAL", "Context", "NotFound", "Proposal", "ProposalError", "Proposals"]
