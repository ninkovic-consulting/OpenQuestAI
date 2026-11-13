"""Maps a tool call to its tier: `free` runs, `ask` waits for the user, `never` refuses.

Tiers are data in `[gate.tiers]`; an unlisted tool gets `[gate] default_tier`.
Some tools can be made stricter by config but never looser: `shell` and a
resident's `run_program` always ask, even if the config says `free`.
"""

from __future__ import annotations

from vision.core.config import GateConfig, Tier

ALWAYS_ASK = frozenset({"shell", "run_program"})
"""Never free: each call waits for a yes, so nothing here runs with nobody to answer."""


def tier_for(gate: GateConfig, tool: str) -> Tier:
    tier = gate.tiers.get(tool, gate.default_tier)
    if tool in ALWAYS_ASK and tier == "free":
        return "ask"
    return tier
