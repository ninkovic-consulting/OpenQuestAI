"""Jobs in words, for the model: one line per job, the details of one, and the report.

The host reads these through its tools and its job turns; the awareness
summary and the house tools use `line` too.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from vision.jobs.model import Job, clip

REPORT_RESULT_MAX = 6000
"""How much of a result the host is given in its job turn."""

_STATUS = {
    "queued": "waiting to start",
    "working": "working",
    "done": "done",
    "failed": "failed",
    "cancelled": "cancelled",
}

Name = Callable[[str], str]


def clock(ts: float | None) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M") if ts else "-"


def line(job: Job, name: Name) -> str:
    """`- 3f2a91c0 "Explain the project" for Tink: working since 14:02 (asked by Vision)`."""
    status = _STATUS[job.status]
    if job.status == "working":
        status += f" since {clock(job.started_at)}"
    elif not job.open:
        status += f" at {clock(job.ended_at)}"
    asked = name(job.asked_by) if job.asked_by not in ("owner",) else "the owner"
    extra = f", a request from {asked} (job {job.parent})" if job.parent else f" (asked by {asked})"
    flag = "; a tool needed a yes that nobody gave" if job.needed_approval else ""
    return f'- {job.id} "{job.title}" for {name(job.agent)}: {status}{extra}{flag}.'


def details(job: Job, name: Name, room: str | None) -> str:
    out = [
        line(job, name).removeprefix("- "),
        f"Room: {room or 'none'}. Careful (heavy model): {'yes' if job.careful else 'no'}. "
        f"Cost so far: ${job.cost_usd:.4f}.",
        f"Brief: {clip(job.brief, 1500)}",
        "Steps:",
        *(f"- {clock(s.ts)} {s.kind}: {s.text}" for s in job.steps[-30:]),
    ]
    if job.result:
        out.append(f"Result: {clip(job.result, 4000)}")
    if job.error:
        out.append(f"Problem: {job.error}")
    return "\n".join(out)


def report(job: Job, name: Name) -> str:
    """What the host's job turn is given: who finished what, and how it went."""
    who = name(job.agent)
    head = f'{who} finished job {job.id}, "{job.title}".'
    if job.status == "failed":
        head = f'{who}\'s job {job.id}, "{job.title}", failed: {job.error}'
    elif job.status == "cancelled":
        head = f'{who}\'s job {job.id}, "{job.title}", was cancelled.'
    lines = [head]
    if job.asked_by == "owner":
        lines.append("The owner started it from the window.")
    if job.needed_approval:
        lines.append("A tool asked for a yes during the work and nobody answered, so it did not run.")
    result = job.result.strip()
    lines.append(f"{who}'s result:\n{clip(result, REPORT_RESULT_MAX)}" if result else "There is no result text.")
    return "\n".join(lines)
