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

Two notes ride on the message too, on that turn only. When several messages
waited while the assistant was busy and go as one turn, it is told so
(`waited_note`): they may add to or correct what it just said. When the
owner cut the last reply off, the next turn says what they heard of it
(`cut_note`), so the assistant neither repeats it nor carries on as if it had
finished.
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


def brain_text(
    text: str,
    origin: TurnOrigin,
    now: datetime,
    surroundings: str = "",
    *,
    images: int = 0,
    waited: int = 0,
    cut: str = "",
) -> str:
    """What the brain is sent for this turn: the words, with the local time when it helps,
    and `surroundings` (a few lines about the house) when the session has new ones. A message
    of `images` with no words is put as the owner sending them, so the brain is asked about them.
    `waited` counts the messages that waited and go together (`waited_note`); `cut` is the
    note about the reply the owner cut off (`cut_note`), or empty."""
    said = _with_time(text or image_only(images), origin, now)
    notes = [n for n in (cut, waited_note(waited, origin.source)) if n]
    if notes:
        said = f"{said}\n\n" + "\n".join(notes)
    return f"{said}\n\n[{surroundings}]" if surroundings else said


def waited_note(count: int, source: str) -> str:
    """Says the words came while the assistant was busy. Typed at the Mac they came while it
    replied, even one; from the phone only several sent in a row need it."""
    if source == "phone":
        if count < 2:
            return ""
        return (
            f"[The owner sent these {count} messages one after another while you were busy, in "
            "this order. Answer them together, in one reply: a later one may add to or correct "
            "an earlier one.]"
        )
    if count < 1:
        return ""
    if count == 1:
        return (
            "[The owner wrote this while you were replying. It may add to or correct what you "
            "just said.]"
        )
    return (
        f"[The owner wrote these {count} messages while you were replying, in this order. Answer "
        "them together, in one reply: they may add to or correct what you just said.]"
    )


CUT_WORDS = 25
"""How much of a cut reply the note quotes: its last words, where the owner stopped hearing."""


def cut_note(heard: str, asked: str) -> str:
    """The note for the turn after the owner cut a reply off: what they heard of it, or,
    when they heard nothing, what it was answering (the brain may not have kept that)."""
    said = heard.split()
    if said:
        tail = " ".join(said[-CUT_WORDS:])
        quoted = tail if len(said) <= CUT_WORDS else f"…{tail}"
        return (
            f'[The owner interrupted your last reply. They heard it only up to: "{quoted}". Do '
            "not carry on from there or repeat it unless they ask; answer what follows.]"
        )
    words = asked.split()
    if not words:
        return "[The owner interrupted your last reply before they heard any of it.]"
    quoted = " ".join(words[:CUT_WORDS]) + ("…" if len(words) > CUT_WORDS else "")
    return (
        f'[The owner interrupted you before you answered "{quoted}", so they heard no reply to '
        "it. Answer what follows; take the earlier message up only if it still matters.]"
    )


def image_only(images: int) -> str:
    """The words for a message that is only images (none for a message with no images)."""
    if images <= 0:
        return ""
    return "The owner sent this image." if images == 1 else f"The owner sent these {images} images."


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
