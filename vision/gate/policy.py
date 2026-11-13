"""Maps a tool call to its tier: `free` runs, `ask` waits for the user, `never` refuses.

Tiers are data in `[gate.tiers]`; an unlisted tool gets `[gate] default_tier`.
Some tools can be made stricter by config but not freely looser:

- the host's `start_project` always asks, even if the config says `free`;
- `shell` may be made `free`, but that holds only for a turn the owner typed
  or said at the Mac. An automation's run, a job report and a turn from the
  phone may carry words the owner did not write, with nobody watching, so
  there `shell` still asks first, at the Mac. Inside a resident's job it
  always asks;
- a resident's `run_program` may be made `free`, but that holds only in a job
  the owner started at the Mac: one the host handed off in a turn the owner
  typed or said there, or one the owner made in the window (which needs the
  local token). A job from the phone, an automation's run, a job report or
  another resident's request, and any job whose origin is not recorded, may
  carry words the owner did not write, so there `run_program` still asks
  first, at the Mac. Free or not, it runs only the owner's programs, without
  a shell, in the project folder.
"""

from __future__ import annotations

from vision.core.config import GateConfig, Tier
from vision.core.events import TurnSource

NEVER_FREE = frozenset({"start_project"})
"""Never free: each call waits for a yes, so nothing here runs with nobody to answer
(`start_project` makes a folder and a room, and may start paid work)."""
FREE_AT_THE_MAC_ONLY = frozenset({"shell"})
"""Free, when so set, only in a turn from `OWNER_AT_THE_MAC`; asks first in any other."""
FREE_FOR_JOBS_FROM_THE_MAC = frozenset({"run_program"})
"""Free, when so set, only in a job whose `via` is in `JOBS_FROM_THE_MAC`; asks first in any other."""
OWNER_AT_THE_MAC: frozenset[TurnSource] = frozenset({"text", "voice"})
"""Turns the owner typed or said at the Mac."""
JOBS_FROM_THE_MAC = frozenset({"text", "voice", "window"})
"""A job's `via` when the owner started it at the Mac: handed off in a turn from
`OWNER_AT_THE_MAC`, or made in the window (`window`). Empty or anything else is not."""


def tier_for(
    gate: GateConfig, tool: str, source: TurnSource | None = None, job_via: str | None = None
) -> Tier:
    """The tier of `tool` in a turn from `source` (None: not the owner's own turn), or in a
    resident's job that was started `job_via` (None: not in a job)."""
    tier = gate.tiers.get(tool, gate.default_tier)
    if tier != "free":
        return tier
    if tool in NEVER_FREE:
        return "ask"
    if tool in FREE_AT_THE_MAC_ONLY and source not in OWNER_AT_THE_MAC:
        return "ask"
    if tool in FREE_FOR_JOBS_FROM_THE_MAC and job_via not in JOBS_FROM_THE_MAC:
        return "ask"
    return tier
