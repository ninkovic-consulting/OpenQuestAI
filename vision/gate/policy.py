"""Maps a tool call to its tier: `free` runs, `ask` waits for the user, `never` refuses.

Tiers are data in `[gate.tiers]`; an unlisted tool gets `[gate] default_tier`.
Some tools can be made stricter by config but not freely looser:

- a resident's `run_program` and the host's `start_project` always ask, even if
  the config says `free`;
- `shell` may be made `free`, but that holds only for a turn the owner typed
  or said at the Mac. An automation's run, a job report and a turn from the
  phone may carry words the owner did not write, with nobody watching, so
  there `shell` still asks first, at the Mac.
"""

from __future__ import annotations

from vision.core.config import GateConfig, Tier
from vision.core.events import TurnSource

NEVER_FREE = frozenset({"run_program", "start_project"})
"""Never free: each call waits for a yes, so nothing here runs with nobody to answer
(`start_project` makes a folder and a room, and may start paid work)."""
FREE_AT_THE_MAC_ONLY = frozenset({"shell"})
"""Free, when so set, only in a turn from `OWNER_AT_THE_MAC`; asks first in any other."""
OWNER_AT_THE_MAC: frozenset[TurnSource] = frozenset({"text", "voice"})
"""Turns the owner typed or said at the Mac."""


def tier_for(gate: GateConfig, tool: str, source: TurnSource | None = None) -> Tier:
    """The tier of `tool` in a turn from `source` (None: not the owner's own turn)."""
    tier = gate.tiers.get(tool, gate.default_tier)
    if tier != "free":
        return tier
    if tool in NEVER_FREE or (tool in FREE_AT_THE_MAC_ONLY and source not in OWNER_AT_THE_MAC):
        return "ask"
    return tier
