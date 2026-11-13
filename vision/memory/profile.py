"""The owner's profile: what to call them, their business, and what to always keep in mind.

Stored as `owner.md` at the top of the vault, a short Markdown file with one
`## ` heading per part, so a person can read and edit it by hand like the
rest of the vault, and backups and resets carry it with the vault. It sits
outside `library/` on purpose: the library is listed and cut to its share of
the memory core, while the profile is always given whole, first.

Every part is optional. Unknown headings and text outside the three parts are
left alone when the file is read and dropped when it is written again.
Blocking; callers use `asyncio.to_thread`.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, fields, replace
from pathlib import Path

FILE_NAME = "owner.md"
LIMITS = {"name": 60, "business": 600, "notes": 2000}
"""Characters each part may hold."""
HEADINGS = {"name": "Call me", "business": "Business", "notes": "Keep in mind"}
_HEADING = re.compile(r"^## +(.+?)[ \t]*$", re.MULTILINE)
_PREAMBLE = (
    "# About the owner\n\n"
    "What the assistant always knows about you. Edit it here or in Settings, Assistant;\n"
    "leave a part empty to clear it.\n"
)


class BadProfile(ValueError):
    """A value that cannot be stored; the message is for people."""


@dataclass(frozen=True, slots=True)
class Profile:
    name: str = ""
    """What the owner asks to be called."""
    business: str = ""
    """The business, its name and what it does, in the owner's words."""
    notes: str = ""
    """Anything else worth always knowing."""

    @property
    def empty(self) -> bool:
        return not (self.name or self.business or self.notes)

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "business": self.business, "notes": self.notes}


FIELDS = tuple(f.name for f in fields(Profile))


def clean(field: str, value: object) -> str:
    """One part, checked: plain text within its length; `name` on one line. Raises `BadProfile`."""
    if field not in LIMITS:
        raise BadProfile(f"The profile has no part called {field!r}; it has {', '.join(FIELDS)}.")
    if not isinstance(value, str):
        raise BadProfile("Send text; an empty text clears the part.")
    text = value.strip().replace("\r\n", "\n")
    allowed = "" if field == "name" else "\n\t"
    if any((ord(c) < 32 and c not in allowed) or ord(c) == 127 for c in text):
        raise BadProfile(
            "What to call you must be one line of plain text."
            if field == "name"
            else "Use plain text, without control characters."
        )
    if field != "name" and re.search(_HEADING, text):
        raise BadProfile("A line may not start with ## here; that marks a part of the file.")
    if len(text) > LIMITS[field]:
        raise BadProfile(f"{_WHAT[field]} can be at most {LIMITS[field]} characters.")
    return text


_WHAT = {"name": "What to call you", "business": "The business", "notes": "What to keep in mind"}


def path_in(vault_root: Path) -> Path:
    return vault_root / FILE_NAME


def read(vault_root: Path) -> Profile:
    """The profile as the file holds it now; an empty one when there is no file.

    A hand edit past a part's limit is cut to the limit, never refused, so the
    assistant always has something to work with.
    """
    try:
        body = path_in(vault_root).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return Profile()
    by_heading = {v.casefold(): k for k, v in HEADINGS.items()}
    parts = _HEADING.split(body)
    found: dict[str, str] = {}
    for heading, text in zip(parts[1::2], parts[2::2], strict=True):
        key = by_heading.get(heading.strip().casefold())
        if key is not None and key not in found:
            value = text.strip()
            if key == "name":
                value = " ".join(value.split())
            found[key] = value[: LIMITS[key]]
    return Profile(**found)


def write(vault_root: Path, profile: Profile) -> None:
    """Write the whole file through a temporary file and a rename, private to the user."""
    target = path_in(vault_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    sections = [_PREAMBLE]
    for key in FIELDS:
        sections.append(f"## {HEADINGS[key]}\n\n{getattr(profile, key)}".rstrip() + "\n")
    temp = target.with_name(f".{target.name}.tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(sections))
    os.replace(temp, target)


def update(vault_root: Path, changes: dict[str, object]) -> Profile:
    """Change only the parts given, after checking every one. Raises `BadProfile`."""
    cleaned = {key: clean(key, value) for key, value in changes.items()}
    now = read(vault_root)
    new = replace(now, **cleaned)
    if new != now or not path_in(vault_root).exists():
        write(vault_root, new)
    return new


# ------------------------------------------------------------------ words for the model


def prompt_text(profile: Profile, *, may_update: bool) -> str:
    """The profile as plain sentences, for the top of a system prompt.

    `may_update` adds how to keep it current (the host has `update_profile`;
    residents do not).
    """
    lines = ["# The owner"]
    if profile.empty:
        lines.append("The owner has not said yet what to call them or what their business is.")
        if may_update:
            lines.append(
                "When they tell you, save it with update_profile. Do not ask out of the blue; "
                "ask only when it fits the conversation."
            )
        return "\n\n".join(lines)
    said: list[str] = []
    if profile.name:
        said.append(f"The owner asks to be called {profile.name}. Address them by that name.")
    if profile.business:
        said.append(f"The business you work for, in the owner's words: {profile.business}")
    if profile.notes:
        said.append(f"The owner asked you to always keep this in mind:\n{profile.notes}")
    lines.append("\n\n".join(said))
    if may_update:
        lines.append(
            "When the owner asks to be called something else, says the business has changed, or "
            "tells you something to always keep in mind, save it with update_profile."
        )
    return "\n\n".join(lines)


def owner_words(profile: Profile) -> str:
    """Who the owner is, in a few words: `Sam; their business: a bakery in Graz`."""
    business = profile.business.splitlines()[0] if profile.business else ""
    if len(business) > 80:
        business = business[:79].rstrip() + "…"
    if profile.name and business:
        return f"{profile.name}; their business: {business}"
    if profile.name:
        return f"{profile.name}; no business given"
    if business:
        return f"no name given; their business: {business}"
    return "not told yet (no name or business given)"


def stored_words(profile: Profile) -> str:
    """What is stored now, part by part, for a tool's answer."""
    return "\n".join(
        f"- {_WHAT[key]}: {getattr(profile, key) or '(empty)'}" for key in FIELDS
    )
