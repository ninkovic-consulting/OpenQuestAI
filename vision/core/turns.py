"""Where the turn in progress came from, and the text the brain is given for it.

The session sets the origin at the start of every turn. It is a context
variable, so everything the turn runs (the brain's tool loop, the gate, the
tools) can read it without being handed it: the gate names the automation on
its card, and the scheduler's tools refuse to let an automation change
automations.

The local time goes into the user's message, never into the cached system
prompt: a typed or spoken turn that mentions a time gets one line with it,
an automation's run says what it is and when it runs, a message from the
paired phone says it came from there, and a job report says a resident's
work ended and that nobody asked anything. The same goes for the short summary
of the house: it rides on the user's message, so the cached prefix never
changes.
"""

from __future__ import annotations

import re
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime

from vision.core.events import TurnSource
from vision.core.localtime import now_words


@dataclass(slots=True)
class TurnOrigin:
    source: TurnSource
    automation_id: str = ""
    automation_name: str = ""
    needed_approval: bool = False
    """Set by the gate when a tool asked first and nobody answered in time."""


_ORIGIN: ContextVar[TurnOrigin | None] = ContextVar("turn_origin", default=None)


def current_origin() -> TurnOrigin | None:
    """The origin of the turn this code runs in, or None outside a turn."""
    return _ORIGIN.get()


def set_origin(origin: TurnOrigin) -> None:
    """Called by the session at the start of a turn, inside the turn's own task."""
    _ORIGIN.set(origin)


_MENTIONS_TIME = re.compile(
    r"\b(remind\w*|schedul\w*|automat\w*|every|daily|weekly|weekdays?|weekends?|tomorrow|tonight"
    r"|today|minutes?|hours?|o'?clock|morning|afternoon|evening|noon|midnight|time|date|when"
    r"|monday|tuesday|wednesday|thursday|friday|saturday|sunday|week|month|later|soon|at \d"
    r"|in (an?|\d+|one|two|three|five|ten|fifteen|twenty|thirty|half)\b|\d{1,2}[:.]\d{2}"
    r"|\d{1,2} ?(am|pm))",
    re.IGNORECASE,
)


def mentions_time(text: str) -> bool:
    return _MENTIONS_TIME.search(text) is not None


def brain_text(text: str, origin: TurnOrigin, now: datetime, surroundings: str = "") -> str:
    """What the brain is sent for this turn: the words, with the local time when it helps,
    and `surroundings` (a few lines about the house) when the session has new ones."""
    said = _with_time(text, origin, now)
    return f"{said}\n\n[{surroundings}]" if surroundings else said


def _with_time(text: str, origin: TurnOrigin, now: datetime) -> str:
    when = now_words(now)
    if origin.source == "automation":
        return (
            f'[Automation "{origin.automation_name}" is due now, {when}. Nobody typed or said '
            "this: it runs on its schedule, perhaps with nobody watching. Carry out the "
            "instruction below and answer with the result in a sentence or two.]\n"
            f"{text}"
        )
    if origin.source == "job":
        return (
            f"[A job report, {when}. Nobody typed or said this: work you or the owner handed to a "
            "resident has ended. Tell the owner the outcome in your own words, in a sentence or "
            "a few, and say plainly if it failed or needed a yes that nobody gave. Do not hand "
            "the work off again unless the owner asks.]\n"
            f"{text}"
        )
    if origin.source == "phone":
        return f"{text}\n\n[Sent from the user's phone, {when}. The reply is read there as a message.]"
    if mentions_time(text):
        return f"{text}\n\n[Local time now: {when}.]"
    return text
