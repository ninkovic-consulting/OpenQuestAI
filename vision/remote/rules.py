"""What goes to the phone, and when: one choice per kind of message.

Each kind is sent `always`, only when the owner is `away` from the Mac
(`vision.presence`), or `never`. A `phone.json` from before the choices held
true or false for each switch: true reads as always, false as never.

Everything here is something the assistant does by itself, so by default
every kind is always sent: it reaches both the app and the phone. A reply to
what the owner typed or said at the Mac is not one of them; it stays at the
Mac. `assistant` covers `send_to_phone`, which sends now whatever the away
state, so for it always and away differ in nothing; never turns it off.
"""

from __future__ import annotations

from typing import Any, Literal

Choice = Literal["always", "away", "never"]
Kind = Literal["automations", "warnings", "approvals", "jobs", "assistant"]

CHOICES: tuple[Choice, ...] = ("always", "away", "never")
KINDS: tuple[Kind, ...] = ("automations", "warnings", "approvals", "jobs", "assistant")
DEFAULTS: dict[Kind, Choice] = {
    "automations": "always",
    "warnings": "always",
    "approvals": "always",
    "jobs": "always",
    "assistant": "always",
}
FIELDS: dict[Kind, str] = {kind: f"notify_{kind}" for kind in KINDS}
"""The `PhoneState` field that holds each kind's choice."""


def read_choice(value: Any) -> Choice:
    """A stored choice, the old true or false included. Raises `TypeError` for anything else."""
    if value is True:
        return "always"
    if value is False:
        return "never"
    if value in CHOICES:
        return value  # type: ignore[no-any-return]
    raise TypeError(f"not a choice: {value!r}")
