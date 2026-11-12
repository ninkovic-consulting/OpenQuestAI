"""What the bot says, in one place."""

from __future__ import annotations

from vision.remote.host import Status

PRIVATE = (
    "This is a private assistant and does not answer here. "
    "If it is yours, send the pairing code from Settings, Phone, on your Mac."
)
"""The one line anyone but the paired owner ever gets."""

STOPPED = "Stopped."
NOTHING_TO_STOP = "Nothing is running."
TOO_MANY = "Still working on your earlier messages. Send this one again in a moment."
ONLY_TEXT = "I can read text and voice notes; other attachments are not read."
CUT_SHORT = "(Stopped before the end.)"
NO_REPLY = "(No reply.)"

VOICE_TOO_LONG = "That voice note is too long for me. Keep it under a few minutes, or type instead."
VOICE_NO_MODELS = (
    "I can't listen to voice notes yet: the speech models are not on the Mac. "
    "Download them in Settings, Voice, then send it again. Typing works now."
)
VOICE_NO_DECODER = (
    "This Mac has nothing that can open voice notes (no soundfile with Opus, no afconvert, "
    "no ffmpeg), so I can't listen to it. Please type instead."
)
VOICE_NOT_FETCHED = "I couldn't download that voice note. Try sending it again."
VOICE_NOT_DECODED = "I couldn't open that voice note. Try again, or type instead."
VOICE_NOT_HEARD = "I couldn't turn that voice note into words. Try again, or type instead."
VOICE_EMPTY = "I couldn't make out any words in that voice note."


def heard(text: str) -> str:
    return f"Heard: “{text}”"


def paired(name: str) -> str:
    return f"Paired. This chat now talks to {name} on your Mac. {help_line()}"


def help_line() -> str:
    return (
        "Send text or a voice note. Plain words: status, stop, help. "
        "Requests that need your yes come here with Yes and Not now buttons; "
        "shell commands are only ever approved at the Mac."
    )


def status_line(s: Status, waiting: int) -> str:
    line = (
        f"{s.name} is {s.state}, answering with {s.brain}. "
        f"This month: ${s.spent_usd:.2f} of ${s.cap_usd:.2f} ({s.month})."
    )
    if waiting:
        line += f" Messages from here waiting: {waiting}."
    return line


def paired_notice(user: str) -> str:
    return f"The phone is paired: {user} can now message the assistant."
