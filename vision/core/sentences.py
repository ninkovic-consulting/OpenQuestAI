"""Incremental sentence splitter for streamed replies.

Feed it text fragments as they arrive; it returns each sentence once the
sentence is certainly finished, so speech can start on the first one.

    splitter = SentenceSplitter()
    splitter.feed("Hello there. How")   # -> ["Hello there."]
    splitter.feed(" are you?")          # -> []  (might continue: "you?!")
    splitter.flush()                    # -> ["How are you?"]

A sentence ends at `.`, `!`, `?` or `…` (plus closing quotes or brackets)
followed by whitespace and more text, or at a line break. It does not end
after a known abbreviation ("Dr.", "e.g."), a single initial ("J."), inside a
number ("3.14"), or at an ellipsis followed by a lowercase word.
"""

from __future__ import annotations

import re

ABBREVIATIONS = frozenset(
    {
        "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "mt", "vs", "etc",
        "e.g", "i.e", "a.m", "p.m", "u.s", "u.k", "inc", "ltd", "co", "corp",
        "approx", "dept", "est", "fig", "no", "vol", "jan", "feb", "mar", "apr",
        "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
    }
)

# Either terminal punctuation, optional closers, whitespace and the next
# character; or a line break followed by more text.
_BOUNDARY = re.compile(r"([.!?…]+)([\"'”’)\]]*)(\s+)(?=(\S))|(\n)\s*(?=\S)")
_WORD_BEFORE = re.compile(r"(\S+)$")


def _ends_sentence(text: str, match: re.Match[str]) -> bool:
    punct, next_char = match.group(1), match.group(4)
    if punct is None or "\n" in match.group(3):
        return True
    is_ellipsis = punct.startswith("...") or punct.startswith("…")
    if is_ellipsis:
        return not next_char.islower()
    if punct != ".":
        return True
    before = _WORD_BEFORE.search(text, 0, match.start(1))
    if before is None:
        return True
    word = before.group(1).lstrip("\"'“‘(").lower()
    if word in ABBREVIATIONS:
        return False
    if len(word) == 1 and word.isalpha():  # an initial: "J. R. R. Tolkien"
        return False
    return True


class SentenceSplitter:
    """Splits a stream of text fragments into whole sentences."""

    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, fragment: str) -> list[str]:
        """Add a fragment; return the sentences it completed, in order."""
        self._buffer += fragment
        out: list[str] = []
        start = 0
        for match in _BOUNDARY.finditer(self._buffer):
            if match.start() < start or not _ends_sentence(self._buffer, match):
                continue
            end = match.end(2) if match.group(1) is not None else match.start()
            sentence = self._buffer[start:end].strip()
            if sentence:
                out.append(sentence)
            start = match.end()
        self._buffer = self._buffer[start:]
        return out

    def flush(self) -> list[str]:
        """Return whatever is left as a final sentence, and reset."""
        rest = self._buffer.strip()
        self._buffer = ""
        return [rest] if rest else []
