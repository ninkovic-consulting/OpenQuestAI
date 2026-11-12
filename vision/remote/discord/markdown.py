"""Discord's markdown, escaped so a reply shows exactly as written.

Discord reads a backslash before any punctuation as "this character as is".
Every character that can start formatting (bold, italics, underline,
strike-through, spoilers, code, quotes, headings, lists, masked links,
mentions and custom emoji) gets one, except inside a bare `http(s)://` link,
which Discord recognises before any formatting and which a backslash would
break. Mentions are also disarmed on every message with
`allowed_mentions: {"parse": []}`, so `@everyone` notifies nobody.
"""

from __future__ import annotations

import re

MAX_CONTENT = 2000
"""Characters in one message."""

_SPECIAL = re.compile(r"([\\*_~`|>#\-\[\]()<])")
_LINK = re.compile(r"https?://[^\s<>]+")


def escape(text: str) -> str:
    out: list[str] = []
    last = 0
    for link in _LINK.finditer(text):
        out.append(_SPECIAL.sub(r"\\\1", text[last : link.start()]))
        out.append(link.group(0))
        last = link.end()
    out.append(_SPECIAL.sub(r"\\\1", text[last:]))
    return "".join(out)


def escaped_length(text: str) -> int:
    return len(escape(text))
