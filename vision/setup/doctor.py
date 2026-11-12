"""`vision doctor`: the checklist as plain text or JSON, and its exit code."""

from __future__ import annotations

import json
from collections.abc import Sequence

from vision.setup.checks import Check

MARK = {"ok": "ok", "missing": "MISSING", "optional": "--"}
TITLE_WIDTH = 22


def all_needed_met(checks: Sequence[Check]) -> bool:
    return all(c.status == "ok" for c in checks if c.needed)


def exit_code(checks: Sequence[Check]) -> int:
    """0 when everything needed is in place, 1 otherwise."""
    return 0 if all_needed_met(checks) else 1


def as_json(checks: Sequence[Check]) -> str:
    return json.dumps(
        {"ok": all_needed_met(checks), "checks": [c.as_dict() for c in checks]}, indent=2
    )


def as_text(checks: Sequence[Check], name: str) -> str:
    lines = [f"OpenQuestAI doctor, for {name}", ""]
    for heading, needed in (("Needed", True), ("Optional", False)):
        lines.append(heading)
        for c in (c for c in checks if c.needed == needed):
            lines.append(f"  {MARK[c.status]:<8} {c.title:<{TITLE_WIDTH}} {c.detail}")
            if c.status != "ok":
                lines.append(f"  {'':<8} {'':<{TITLE_WIDTH}} for {c.needed_for}")
                lines.append(f"  {'':<8} {'':<{TITLE_WIDTH}} fix: {c.fix}")
        lines.append("")
    if all_needed_met(checks):
        lines.append("Everything needed is in place.")
    else:
        lines.append("Something needed is missing; see MISSING above.")
    return "\n".join(lines)
